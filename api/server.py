#!/usr/bin/env python3
"""solve.run combo-index — the API service.

Standard library only (http.server, json, urllib, threading, hashlib, base64).
No Flask, no FastAPI, no pip installs — because the whole point is that the dataset
outlives the service, and the service should be as close to zero-dependency as the
static file it fronts.

Routes
------
Static (from web/, --static-dir):
    GET /                          web/index.html
    GET /<path>                    web/<path>  (traversal-blocked)

Read (side-effect free — safe for agents to poll):
    GET /api/lookup?hw=&model=&runtime=&status=&kind=&q=&limit=   CONTRACT §4
    GET /api/rows?...&offset=      filtered browse + counts
    GET /api/wanted                wanted rows, votes desc then want_first asc
    GET /api/combos.json           the export (ETag, Cache-Control, 304)
    GET /api/export.jsonl          full dump as JSONL (ETag, Cache-Control, 304)
    GET /api/taxonomy              vendors / runtimes / models / hw_archs
    GET /api/health                liveness + dataset freshness + write-path health
    GET /api/docs                  human-readable integration doc (HTML)
    GET /api/openapi.json          machine-readable spec

Write:
    POST /api/want/{id}            {"voter": "<stable key>"} -> 201/200, idempotent
    DELETE /api/want/{id}          same body — retract
    POST /api/miss                 {"query": {...}, "searcher_key": "..."} -> logs
    GET  /api/lookup?...&log=1     logs the miss (opt-in; GET is otherwise pure)

Design decisions worth knowing
------------------------------
* GET /api/lookup never writes unless `log=1`. Agents poll; a poll must not invent
  a demand signal.
* POST /api/want works for any CONTRACT-valid id, even one the pipeline has not
  exported yet — that is how a "want this" button on a miss panel can be useful
  before the row exists. The vote is stored in data/votes.json; the pipeline folds it.
* Votes are idempotent per (id, voter): the stored count is the size of the
  requester set, never a separate tally, so a double-clicked button cannot inflate it.
* Above 3 distinct searchers on the same query_id, the write path asks the pipeline
  to rebuild. If that fails it is logged and the API keeps serving: the read path
  must not die with the write path.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import mimetypes
import os
import posixpath
import re
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import store as store_mod  # noqa: E402
import views as views_mod  # noqa: E402
import docs as docs_mod  # noqa: E402
import openapi as openapi_mod  # noqa: E402

VERSION = "0.1.0"
RATE_LIMIT_PER_MIN = 20
VOTER_RE = re.compile(r"^[\w.:@/+\-]{1,120}$")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
    ".woff2": "font/woff2",
}

CACHE_LONG = "public, max-age=3600"
CACHE_STATIC = "no-cache"


# --------------------------------------------------------------------------
# rate limiting (in-memory, per process — honest about being best-effort)
# --------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, limit: int = RATE_LIMIT_PER_MIN, window_s: float = 60.0):
        self.limit = limit
        self.window = window_s
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            bucket = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(bucket) >= self.limit:
                retry = max(1, int(self.window - (now - bucket[0])) + 1)
                self._hits[key] = bucket
                return False, retry
            bucket.append(now)
            self._hits[key] = bucket
            if len(self._hits) > 4096:  # keep the dict from growing without bound
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    self._hits.pop(k, None)
            return True, 0


# --------------------------------------------------------------------------
# handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = f"solve-run-index/{VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # injected by make_server
    store: store_mod.Store
    static_dir: str
    limiter: RateLimiter
    quiet: bool = False

    # -- logging -----------------------------------------------------------

    def log_message(self, fmt, *args):  # noqa: A003
        if self.quiet:
            return
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        sys.stderr.write(f"{ts} {self.address_string()} {fmt % args}\n")

    def log_error(self, fmt, *args):
        self.log_message(fmt, *args)

    # -- primitives --------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None,
              head_only: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, If-None-Match")
        self.send_header("Access-Control-Expose-Headers", "ETag, X-Dataset-Version, X-Row-Count")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head_only:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, status: int, obj, extra: dict | None = None, head_only: bool = False) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra, head_only)

    def _error(self, status: int, code: str, message: str, **extra) -> None:
        payload = {"error": {"code": code, "status": status, "message": message}}
        payload.update(extra)
        self._json(status, payload)

    def _client_ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For")
        if fwd:  # behind Caddy; first hop is the client
            return fwd.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "0.0.0.0"

    def _read_json_body(self, limit: int = 64 * 1024):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "invalid Content-Length"
        if length > limit:
            return None, "body too large"
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}, None
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return None, f"invalid JSON: {exc}"
        if not isinstance(obj, dict):
            return None, "body must be a JSON object"
        return obj, None

    def _etag_matches(self, etag: str) -> bool:
        inm = self.headers.get("If-None-Match")
        if not inm:
            return False
        for candidate in inm.split(","):
            c = candidate.strip()
            if c == "*" or c == etag or c == f"W/{etag}":
                return True
        return False

    def _serve_bytes_cached(self, status: int, data: bytes, content_type: str,
                            etag: str, cache: str, extra: dict | None = None) -> None:
        headers = {"ETag": etag, "Cache-Control": cache}
        headers.update(extra or {})
        if self._etag_matches(etag):
            self._send(304, b"", content_type, headers, head_only=True)
            return
        self._send(status, data, content_type, headers, head_only=(self.command == "HEAD"))

    # -- routing -----------------------------------------------------------

    def do_OPTIONS(self):  # noqa: N802
        self._send(204, b"", "text/plain; charset=utf-8")

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    # BaseException (not Exception) on purpose: a pipeline module calling sys.exit()
    # raises SystemExit, and that must not take a request thread down mid-response.
    def do_GET(self):  # noqa: N802
        try:
            self._route_get()
        except BaseException as exc:  # noqa: BLE001 — never leak a traceback to a client
            self._internal_error(exc)

    def do_POST(self):  # noqa: N802
        try:
            self._route_write("POST")
        except BaseException as exc:  # noqa: BLE001
            self._internal_error(exc)

    def do_DELETE(self):  # noqa: N802
        try:
            self._route_write("DELETE")
        except BaseException as exc:  # noqa: BLE001
            self._internal_error(exc)

    def _internal_error(self, exc: Exception) -> None:
        sys.stderr.write(f"[api] ERROR {self.command} {self.path}: {type(exc).__name__}: {exc}\n")
        try:
            self._error(500, "internal", f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001 — headers may already be sent
            pass

    def _parse(self) -> tuple[str, dict]:
        parsed = urllib.parse.urlsplit(self.path)
        path = posixpath.normpath(urllib.parse.unquote(parsed.path or "/"))
        if parsed.path.endswith("/") and path != "/":
            path += "/"
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        return path, params

    def _route_get(self):
        path, params = self._parse()
        if path == "/api" or path == "/api/":
            return self._index()
        if path.startswith("/api/"):
            return self._api_get(path, params)
        return self._static(path)

    def _route_write(self, method: str):
        path, params = self._parse()
        if method == "POST" and path == "/api/miss":
            return self._post_miss()
        if method == "POST" and path == "/api/lookup":
            # a POST lookup is an explicit "I am searching" — it logs misses
            body, err = self._read_json_body()
            if err:
                return self._error(400, "bad-request", err)
            merged = dict(params)
            for k, v in ((body.get("query") or body) if isinstance(body, dict) else {}).items():
                if isinstance(v, (str, int, float)) and k in store_mod.QUERY_KEYS:
                    merged[k] = [str(v)]
            return self._do_lookup(merged, log_miss=True)
        m = re.fullmatch(r"/api/want/(.+)", path)
        if m:
            row_id = urllib.parse.unquote(m.group(1)).strip("/")
            return self._do_vote(row_id, add=(method == "POST"))
        if path.startswith("/api/"):
            return self._error(405, "method-not-allowed", f"{method} not allowed on {path}")
        return self._error(405, "method-not-allowed", f"{method} not allowed on {path}")

    # -- API: read ---------------------------------------------------------

    def _api_get(self, path: str, params: dict):
        if path == "/api/lookup":
            return self._do_lookup(params, log_miss=False)
        if path == "/api/rows":
            return self._do_rows(params)
        if path in ("/api/wanted", "/api/untested"):
            q = store_mod.parse_query(params)
            ds = self.store.dataset()
            rows = views_mod.wanted_rows(self.store, q)
            return self._json(200, {
                "rows": rows[:(q.get("limit") or store_mod.DEFAULT_LIMIT)],
                "count": len(rows),
                "want_votes_total": sum(int(r.get("want_votes") or 0) for r in rows),
                "sort": "want_votes desc, want_first asc",
                "dataset": ds.meta(),
                "generated_at": store_mod._utcnow(),
            })
        if path == "/api/combos.json":
            data, etag, meta = self.store.combos_bytes()
            if data is None:
                return self._error(503, "no-data",
                                   (self.store.dataset().error or "no export yet"),
                                   hint="run `python3 scripts/serve.py` or `python3 pipeline/build.py`")
            return self._serve_bytes_cached(200, data, "application/json; charset=utf-8",
                                            etag, CACHE_LONG,
                                            {"X-Dataset-Version": str(meta.get("version") or ""),
                                             "X-Row-Count": str(meta.get("rows") or 0)})
        if path == "/api/export.jsonl":
            data, etag = self.store.export_bytes()
            if data is None:
                return self._error(503, "no-data", (self.store.dataset().error or "no export yet"))
            return self._serve_bytes_cached(200, data, "application/x-ndjson; charset=utf-8",
                                            etag, CACHE_LONG,
                                            {"Content-Disposition": 'inline; filename="export.jsonl"'})
        if path == "/api/taxonomy":
            tx = self.store.taxonomy()
            if not tx:
                return self._error(503, "no-data", "data/taxonomy.json missing or unreadable")
            # `runtime_id_aliases` lets a client translate an id segment back to the
            # display slug: ids may not contain dots, so vote rows carry `llama_cpp`
            # while the taxonomy slug is `llama.cpp`.
            payload = dict(tx)
            payload.setdefault("runtime_id_aliases", store_mod.runtime_alias_map(tx))
            blob = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
            return self._serve_bytes_cached(
                200, blob, "application/json; charset=utf-8",
                store_mod.etag_for(json.dumps(payload, ensure_ascii=False,
                                               sort_keys=True).encode("utf-8")),
                CACHE_LONG)
        if path == "/api/health":
            return self._health()
        if path == "/api/docs":
            html = docs_mod.render_html(self.store, base_url=self._base_url())
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8",
                              {"Cache-Control": "no-cache"})
        if path == "/api/openapi.json":
            spec = openapi_mod.spec(base_url=self._base_url())
            return self._json(200, spec, {"Cache-Control": CACHE_LONG})
        # An unknown /api/* path is a client bug: say 404 + JSON, never fall through
        # to the web index (that makes typos look like success to an agent).
        return self._error(404, "not-found", f"no such API route: {path}",
                           hint="GET /api lists every route; GET /api/docs explains them")

    def _index(self):
        ds = self.store.dataset()
        self._json(200, {
            "service": "solve.run combo-index",
            "version": VERSION,
            "contract": "CONTRACT.md §4",
            "dataset": ds.meta(),
            "routes": ["/api/lookup", "/api/rows", "/api/wanted", "/api/untested", "/api/combos.json",
                       "/api/export.jsonl", "/api/taxonomy", "/api/health", "/api/docs",
                       "/api/openapi.json", "POST /api/want/{id}", "DELETE /api/want/{id}",
                       "POST /api/miss"],
            "docs": "/api/docs",
        })

    def _health(self):
        ds = self.store.dataset()
        data_ok = bool(ds.rows) and not ds.error
        votes = self.store.votes()
        miss_count = len(self.store.miss_records())
        stale_days = None
        as_of = ds.meta().get("as_of")
        if as_of and store_mod._DATE_RE.match(str(as_of)):
            try:
                d = _dt.date.fromisoformat(str(as_of))
                stale_days = (_dt.datetime.now(_dt.timezone.utc).date() - d).days
            except ValueError:
                pass
        status = 200 if data_ok else 503
        self._json(status, {
            "ok": data_ok,
            "version": VERSION,
            "now": store_mod._utcnow(),
            "dataset": ds.meta(),
            "dataset_ok": data_ok,
            "dataset_error": ds.error,
            "dataset_source": ds.source,
            "stale_days": stale_days,
            "write_path": {
                "votes": len(votes),
                "vote_count_total": sum(int((v or {}).get("count") or 0) for v in votes.values()),
                "misses": miss_count,
                "votes_file": self.store.votes_path,
                "misses_file": self.store.misses_path,
                "recent_errors": self.store.errors[-5:],
            },
            "build": {"pipeline_present": os.path.exists(os.path.join(ROOT, "pipeline", "build.py")),
                      "python": sys.version.split()[0]},
        })

    def _do_lookup(self, params: dict, *, log_miss: bool):
        query = store_mod.parse_query(params)
        payload = views_mod.lookup_payload(self.store, query)

        wants_log = str((params.get("log") or [""])[0] or "").lower() in ("1", "true", "yes")
        if log_miss or wants_log:
            if payload["miss"].get("is_miss"):
                searcher = str((params.get("searcher") or [""])[0] or "").strip()
                searcher = searcher or self._searcher_key()
                result = self._record_miss(query, payload["query_id"], searcher)
                payload["miss_logged"] = result
            else:
                payload["miss_logged"] = {"logged": False, "reason": "not-a-miss"}

        headers = {"Cache-Control": "no-store",
                   "X-Query-Id": payload["query_id"],
                   "X-Dataset-Version": str(payload["dataset"].get("version") or "")}
        self._json(200, payload, headers)

    def _do_rows(self, params: dict):
        query = store_mod.parse_query(params)
        try:
            offset = int(str((params.get("offset") or ["0"])[0]) or 0)
        except ValueError:
            offset = 0
        offset = max(0, offset)
        self._json(200, views_mod.browse(self.store, query, offset), {"Cache-Control": "no-store"})

    def _searcher_key(self) -> str:
        """Anonymous, stable-per-client, non-reversible key. IP is never stored in clear."""
        ip = self._client_ip()
        ua = self.headers.get("User-Agent") or ""
        import hashlib
        digest = hashlib.sha256(f"{ip}|{self.server.salt}|{ua}".encode("utf-8")).hexdigest()
        return "anon:" + digest[:16]

    def _record_miss(self, query: dict, query_id: str, searcher: str) -> dict:
        allowed, retry = self.limiter.allow(f"miss:{self._client_ip()}")
        if not allowed:
            return {"logged": False, "reason": "rate-limited", "retry_after": retry}
        result = self.store.log_miss(query, searcher,
                                     user_agent=self.headers.get("User-Agent") or "",
                                     query_id=query_id)
        if result["distinct_searchers"] >= store_mod.CREATES_WANTED_AT:
            result["pipeline_rebuild"] = self.store.schedule_rebuild()
        return result

    # -- API: write --------------------------------------------------------

    def _do_vote(self, row_id: str, *, add: bool):
        path = urllib.parse.urlsplit(self.path).path
        if "/api/want/" not in path:
            return self._error(404, "not-found", path)
        if not row_id or len(row_id) > 300:
            return self._error(400, "bad-id", "row id missing or too long")

        body, err = self._read_json_body()
        if err:
            return self._error(400, "bad-request", err)
        voter = str((body or {}).get("voter") or "").strip()
        if not voter:
            voter = str((body or {}).get("searcher_key") or "").strip()
        if not voter:
            # anonymous fallback: a device-stable key derived per IP+UA, clearly labelled
            voter = self._searcher_key()
        if not VOTER_RE.match(voter):
            return self._error(400, "bad-voter", "voter must be 1-120 chars of [A-Za-z0-9._:@/+-]")

        allowed, retry = self.limiter.allow(f"vote:{self._client_ip()}")
        if not allowed:
            return self._json(429, {
                "error": {"code": "rate-limited", "status": 429,
                          "message": f"{RATE_LIMIT_PER_MIN} vote writes/min per IP"},
                "retry_after": retry,
            }, {"Retry-After": str(retry)})

        # Validate with the pipeline's own id rules before recording anything: the
        # pipeline materialises a vote into a stored row from the id's segments, so a
        # garbage id would become a vote-orphan (demand that produces no row).
        #
        # 1. Structural shape first: 4 non-empty segments (base) or 5 (variant /@slug).
        parts = row_id.split("/")
        if len(parts) not in (4, 5) or not all(parts):
            return self._json(400, {"error": {
                "code": "bad-id", "status": 400, "id": row_id,
                "message": f"id: {row_id!r} is not of the form vendor/arch/model/runtime[/@slug]",
                "hint": "see CONTRACT.md §2",
            }}, {"Cache-Control": "no-store"})
        if len(parts) == 5 and not store_mod._VARIANT_SLUG_RE.match(parts[4]):
            return self._json(400, {"error": {
                "code": "bad-id", "status": 400, "id": row_id,
                "message": f"variant slug {parts[4]!r} must match ^@[a-z0-9][a-z0-9_-]*$",
                "hint": "see CONTRACT.md §2",
            }}, {"Cache-Control": "no-store"})

        # 2. The runtime segment is resolved against the taxonomy (either spelling
        #    accepted) and the id re-written to the single canonical spelling, so the
        #    materialised row's `runtime` field is the one the pipeline would derive.
        stored_id, runtime_slug, known_runtimes, _segment = store_mod.canonical_vote_id(
            row_id, self.store.taxonomy())
        if runtime_slug is None:
            return self._json(400, {"error": {
                "code": "unknown-runtime",
                "status": 400,
                "message": (f"runtime {row_id.split('/')[3]!r} is not a runtime in data/taxonomy.json "
                            "and is not a dot-collapsed form of one"),
                "id": row_id,
                "known_runtimes": known_runtimes,
                "hint": "use a runtime slug from /api/taxonomy, with dots flattened to '_' in ids",
            }}, {"Cache-Control": "no-store"})

        # 3. Canonicality of the resolved id: lowercase, dot-free segments.
        ok, why, _segments = store_mod.validate_row_id(stored_id)
        if not ok:
            body = {"message": why, "id": row_id}
            canonical = self._canonical_id_hint(row_id)
            if canonical:
                body["did_you_mean"] = canonical
            return self._json(400, {"error": dict(code="bad-id", status=400, **body)},
                              {"Cache-Control": "no-store"})

        existing = self.store.row_by_id(stored_id)

        result = self.store.vote(stored_id, voter, add=add)
        result["status"] = (existing or {}).get("status") or ("untested" if result["want_votes"] else None)
        result["row_known"] = existing is not None
        result["runtime"] = runtime_slug
        if stored_id != row_id:
            result["id_requested"] = row_id

        if result["want_votes"] >= store_mod.CREATES_WANTED_AT:
            result["pipeline_rebuild"] = self.store.schedule_rebuild()

        status = 201 if result["voted"] and add else 200
        self._json(status, result, {"Cache-Control": "no-store", "X-Row-Id": row_id})

    def _canonical_id_hint(self, row_id: str) -> str | None:
        """If the id is merely non-canonical, tell the client the id we would store."""
        schema = store_mod._schema_module()
        if schema is None:
            return None
        try:
            seg = schema.parse_id(row_id)
            return schema.derive_id(seg["hw_vendor"], seg["hw_arch"],
                                    seg["model_family"], seg["runtime"])
        except Exception:  # noqa: BLE001 — no sensible suggestion
            return None

    def _post_miss(self):
        body, err = self._read_json_body()
        if err:
            return self._error(400, "bad-request", err)
        query_in = body.get("query")
        if not isinstance(query_in, dict) or not query_in:
            return self._error(400, "bad-request",
                               'body must be {"query": {...}, "searcher_key": "..."}')
        unknown = [k for k in query_in if k not in store_mod.QUERY_KEYS]
        if unknown:
            return self._error(400, "bad-query", f"unknown query keys: {unknown}",
                               allowed=list(store_mod.QUERY_KEYS))
        query = store_mod.parse_query({k: str(v) for k, v in query_in.items() if v is not None})
        searcher = str(body.get("searcher_key") or "").strip() or self._searcher_key()
        if not VOTER_RE.match(searcher):
            return self._error(400, "bad-voter", "searcher_key must be 1-120 url-ish chars")
        result = self._record_miss(query, store_mod.query_id_for(query), searcher)
        result["creates_wanted_at"] = store_mod.CREATES_WANTED_AT
        status = 200 if result.get("logged") else 429
        self._json(status, result, {"Cache-Control": "no-store"})

    # -- static ------------------------------------------------------------

    def _static(self, path: str):
        if self.command not in ("GET", "HEAD"):
            return self._error(405, "method-not-allowed", "static files are read-only")
        static_root = os.path.realpath(self.static_dir)
        rel = path.lstrip("/")
        if rel in ("", "."):
            rel = "index.html"

        # Backwards-compatible aliases so old links / the blueprint's URLs still work.
        # Values are handler names resolved by _api_alias (not file paths).
        aliases = {
            "v1/lookup": "lookup",
            "v1/export.jsonl": "export.jsonl",
            "v1/combos.json": "combos.json",
            "combo.json": "lookup",
            "lookup": "lookup",
            "export.jsonl": "export.jsonl",
            "combos.json": "combos.json",
            "wanted": "wanted",
        }
        if rel in aliases:
            return self._api_alias(aliases[rel], path)

        candidate = os.path.realpath(os.path.join(static_root, rel))
        if not (candidate == static_root or candidate.startswith(static_root + os.sep)):
            return self._error(404, "not-found", "path outside the static root",
                               path=path)
        if os.path.isdir(candidate):
            index = os.path.join(candidate, "index.html")
            if os.path.isfile(index):
                candidate = index
            else:
                return self._error(404, "not-found", "directory listing disabled", path=path)
        if not os.path.isfile(candidate):
            # single-page fallback: the UI is a SPA-ish app; unknown paths render index
            index = os.path.join(static_root, "index.html")
            if os.path.isfile(index) and not os.path.splitext(rel)[1]:
                candidate = index
            else:
                return self._error(404, "not-found", f"no such file: {rel}", path=path)

        try:
            with open(candidate, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            return self._error(500, "io", f"could not read {rel}: {exc}")

        ext = os.path.splitext(candidate)[1].lower()
        ctype = CONTENT_TYPES.get(ext) or mimetypes.guess_type(candidate)[0] or "application/octet-stream"
        etag = store_mod.etag_for(data)
        if self._etag_matches(etag):
            self._send(304, b"", ctype, {"ETag": etag, "Cache-Control": CACHE_STATIC}, head_only=True)
            return
        self._send(200, data, ctype, {"ETag": etag, "Cache-Control": CACHE_STATIC},
                   head_only=(self.command == "HEAD"))

    def _api_alias(self, name: str, original_path: str):
        """Map legacy paths (/v1/lookup, /combo.json) onto the /api handlers."""
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query,
                                       keep_blank_values=True)
        if name == "lookup":
            return self._do_lookup(params, log_miss=False)
        if name == "wanted":
            q = store_mod.parse_query(params)
            rows = views_mod.wanted_rows(self.store, q)
            return self._json(200, {"rows": rows, "count": len(rows),
                                    "dataset": self.store.dataset().meta()})
        if name == "export.jsonl":
            data, etag = self.store.export_bytes()
            if data is None:
                return self._error(503, "no-data", "no export yet")
            return self._serve_bytes_cached(200, data, "application/x-ndjson; charset=utf-8",
                                            etag, CACHE_LONG)
        if name == "combos.json":
            data, etag, meta = self.store.combos_bytes()
            if data is None:
                return self._error(503, "no-data", "no export yet")
            return self._serve_bytes_cached(200, data, "application/json; charset=utf-8",
                                            etag, CACHE_LONG)
        return self._error(404, "not-found", original_path)

    # -- helpers -----------------------------------------------------------

    def _base_url(self) -> str:
        host = self.headers.get("Host")
        if not host:
            host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        scheme = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip()
        return f"{scheme}://{host}"


# --------------------------------------------------------------------------
# server factory
# --------------------------------------------------------------------------

class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, handler, *, data_dir: str, static_dir: str, quiet: bool = False,
                 rate_limit: int = RATE_LIMIT_PER_MIN):
        self.store = store_mod.Store(data_dir)
        self.static_dir = os.path.abspath(static_dir)
        self.salt = os.urandom(16).hex()  # restart-scoped: anon searcher keys rotate
        self.limiter = RateLimiter(rate_limit)
        h = type("BoundHandler", (handler,), {
            "store": self.store,
            "static_dir": self.static_dir,
            "limiter": self.limiter,
            "quiet": quiet,
        })
        self.RequestHandlerClass = h
        super().__init__(addr, h)


def make_server(host: str = "127.0.0.1", port: int = 8787, *, data_dir: str | None = None,
                static_dir: str | None = None, quiet: bool = False,
                rate_limit: int = RATE_LIMIT_PER_MIN) -> Server:
    data_dir = os.path.abspath(data_dir or os.path.join(ROOT, "data"))
    static_dir = os.path.abspath(static_dir or os.path.join(ROOT, "web"))
    return Server((host, port), Handler, data_dir=data_dir, static_dir=static_dir,
                  quiet=quiet, rate_limit=rate_limit)


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="solve.run combo-index API server (stdlib only)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787,
                    help="port; 0 picks a free one (used by the tests)")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--static-dir", default=os.path.join(ROOT, "web"))
    ap.add_argument("--quiet", action="store_true", help="silence request logging")
    ap.add_argument("--rate-limit", type=int, default=RATE_LIMIT_PER_MIN,
                    help="write requests per minute per IP (default 20)")
    args = ap.parse_args(argv)

    if not _port_free(args.host, args.port) and args.port != 0:
        sys.stderr.write(
            f"[api] port {args.port} is already in use on {args.host}. "
            f"Something is already serving there — try it, or pick --port {args.port + 1}.\n")
        return 2

    srv = make_server(args.host, args.port, data_dir=args.data_dir,
                      static_dir=args.static_dir, quiet=args.quiet,
                      rate_limit=args.rate_limit)
    host, port = srv.server_address[0], srv.server_address[1]
    ds = srv.store.dataset()
    print(f"[api] listening on http://{host}:{port}")
    print(f"[api] data   {srv.store.data_dir}  ({len(ds.rows)} rows"
          f"{', as_of ' + str(ds.meta().get('as_of')) if ds.meta().get('as_of') else ''}"
          f"{'; ' + ds.error if ds.error else ''})")
    print(f"[api] static {srv.static_dir}")
    print(f"[api] docs   http://{host}:{port}/api/docs")
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[api] bye")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
