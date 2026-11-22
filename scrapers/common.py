"""Shared helpers for the solve.run combo-index scrapers.

Contract highlights (see CONTRACT.md §1):
  - every row needs: id, status, source_kind, hw_vendor, hw_arch, model_family,
    runtime, as_of, reported_by, pointer_alive, want_votes, want_first,
    want_requesters, evidence[].
  - `as_of` is the date the evidence was observed (date of this scrape run).
  - `first_seen` / `updated` are deliberately NOT emitted by scrapers
    (CONTRACT §1: "set by the pipeline, not by scrapers"); optional so they are left out.

Network:
  - one request per second per host, a shared UA, on-disk cache used with --offline.
  - 403/429 rate limits are recorded, backed off, and reported in runs.jsonl instead of
    crashing the run.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "scrapers" / "cache"
OUT = ROOT / "scrapers" / "out"
UA = "solve.run-index/0.1 (+combo index; contact via repo)"

# today's date, frozen once per process so one run produces one as_of everywhere
AS_OF = os.environ.get("SCRAPER_AS_OF") or _dt.date.today().isoformat()

VENDORS = {"nvidia", "amd", "intel", "apple", "qualcomm", "arm-cpu", "x86-cpu", "other"}
RUNTIME_SLUGS = {r["slug"] for r in json.loads(
    (ROOT / "data" / "taxonomy.json").read_text())["runtimes"]}
TAXONOMY = json.loads((ROOT / "data" / "taxonomy.json").read_text())


# --------------------------------------------------------------------------- HTTP
class Http:
    """Tiny shared HTTP client: 1 req/s per host, cache keyed on url hash."""

    def __init__(self, source_key: str, offline: bool = False):
        self.source_key = source_key
        self.offline = offline
        self.cacheref = CACHE / source_key
        self.cacheref.mkdir(parents=True, exist_ok=True)
        self.status_counts: dict[str, int] = {}
        self.errors: list[str] = []
        self._last_req: dict[str, float] = {}
        self.rows_in = 0

    # -- cache
    def _path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[1])[:90]
        return self.cacheref / f"{slug}.{h}.cache"

    def _bump(self, status) -> None:
        k = str(status)
        self.status_counts[k] = self.status_counts.get(k, 0) + 1

    def get(self, url: str, *, ttl_s: int = 6 * 3600, headers: dict | None = None,
            retries: int = 2) -> bytes | None:
        """Return body bytes or None. Cached body wins when offline or still fresh."""
        p = self._path(url)
        cached_meta = None
        if p.exists():
            try:
                blob = json.loads(p.read_text())
                cached_meta = blob
            except Exception:
                blob, cached_meta = None, None
        if self.offline:
            if cached_meta and cached_meta.get("body_b64") is not None:
                self._bump("offline-cache")
                import base64
                return base64.b64decode(cached_meta["body_b64"])
            self.errors.append(f"offline-miss {url}")
            return None
        if cached_meta and time.time() - cached_meta.get("ts", 0) < ttl_s:
            self._bump("cache-hit")
            import base64
            return base64.b64decode(cached_meta["body_b64"])

        host = url.split("/")[2]
        for attempt in range(retries + 1):
            self._throttle(host)
            hdrs = {"User-Agent": UA}
            gh_token = os.environ.get("GITHUB_TOKEN")
            if gh_token and "api.github.com" in url:
                hdrs["Authorization"] = f"Bearer {gh_token}"
            if cached_meta and cached_meta.get("etag"):
                hdrs["If-None-Match"] = cached_meta["etag"]
            if headers:
                hdrs.update(headers)
            try:
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
                    etag = r.headers.get("ETag")
                    status = r.status
                self._bump(status)
                self._store(p, url, body, etag)
                return body
            except urllib.error.HTTPError as e:
                self._bump(e.code)
                if e.code == 304 and cached_meta:
                    cached_meta["ts"] = time.time()
                    p.write_text(json.dumps(cached_meta))
                    import base64
                    return base64.b64decode(cached_meta["body_b64"]) if cached_meta.get("body_b64") else None
                if e.code in (403, 429):
                    wait = 20 * (attempt + 1)
                    self.errors.append(f"{e.code} rate-limited {url} (sleep {wait}s)")
                    time.sleep(wait)
                    continue
                if e.code in (404, 410):
                    self.errors.append(f"{e.code} {url}")
                    return None
                if 500 <= e.code < 600 and attempt < retries:
                    time.sleep(5 * (attempt + 1))
                    continue
                self.errors.append(f"{e.code} {url}")
                return None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                self._bump("neterr")
                self.errors.append(f"net {type(e).__name__} {url}")
                if attempt < retries:
                    time.sleep(5 * (attempt + 1))
                    continue
                return None
        # all retries exhausted -> fall back to stale cache rather than fail
        if cached_meta and cached_meta.get("body_b64"):
            import base64
            self.errors.append(f"stale-cache-fallback {url}")
            return base64.b64decode(cached_meta["body_b64"])
        return None

    def get_json(self, url: str, **kw):
        b = self.get(url, **kw)
        if b is None:
            return None
        try:
            return json.loads(b)
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"bad-json {url}: {e}")
            return None

    def get_text(self, url: str, **kw) -> str | None:
        b = self.get(url, **kw)
        return None if b is None else b.decode("utf-8", "replace")

    def _store(self, p: Path, url: str, body: bytes, etag: str | None):
        import base64
        p.write_text(json.dumps({
            "url": url, "ts": time.time(), "etag": etag,
            "body_b64": base64.b64encode(body).decode(), "nbytes": len(body),
        }))

    def _throttle(self, host: str):
        last = self._last_req.get(host, 0.0)
        dt = 1.05 - (time.time() - last)
        if dt > 0:
            time.sleep(dt)
        self._last_req[host] = time.time()


# ------------------------------------------------------------------ row building
def slugify(s: str) -> str:
    """id segment slug: lowercase [a-z0-9] joined by '-' or '_' (CONTRACT §2, no dots)."""
    s = s.lower().replace(".", "-")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def id_seg(s: str) -> str:
    """id segment: lowercase, dots -> underscores, everything else passes through."""
    return str(s).lower().replace(".", "_")


def make_id(hw_vendor, hw_arch, model_family, runtime) -> str:
    return "/".join(id_seg(x) for x in (hw_vendor, hw_arch, model_family, runtime))


def make_row(*, hw_vendor, hw_arch, model_family, runtime, status, source_kind,
             evidence, reported_by, notes=None, pointer=None, hw_name=None,
             hw_extra=None, model_rev=None, quant=None, runtime_rev=None,
             missing=None, measurement=None, created_by="scraper",
             pointer_alive=True, provisional=None, as_of=None):
    ev = []
    for e in evidence:
        assert e.get("url") and e.get("quote"), f"evidence without url/quote: {e}"
        ev.append({"url": e["url"], "quote": e["quote"], "kind": e.get("kind", "upstream-doc")})
    row = {
        # CONTRACT §2 (lead correction 2026-11-22): `runtime`/`model_family` keep the
        # taxonomy slug verbatim, but id segments never contain dots: "." -> "_".
        "id": make_id(hw_vendor, hw_arch, model_family, runtime),
        "status": status,
        "source_kind": source_kind,
        "hw_vendor": hw_vendor,
        "hw_arch": hw_arch,
        "hw_extra": hw_extra or {},
        "model_family": model_family,
        "model_rev": model_rev,
        "quant": quant,
        "runtime": runtime,
        "runtime_rev": runtime_rev,
        "pointer": pointer,
        "notes": notes,
        "measurement": measurement,
        "pointer_alive": pointer_alive,
        "as_of": as_of or AS_OF,
        "reported_by": reported_by,
        "want_votes": 0,
        "want_first": None,
        "want_requesters": [],
        "evidence": ev,
        "missing": list(missing or []),
        "created_by": created_by,
    }
    if hw_name:
        row["hw_name"] = hw_name
    if provisional is not None:
        row["provisional"] = provisional
    return row


def verbatim(source_text: str, needle: str) -> str:
    """Return `needle` only if it occurs verbatim in the fetched text (else raise).

    This is the anti-fabrication guard: a quote we cannot find in the live document is
    never emitted.
    """
    if needle in source_text:
        return needle
    # tolerate whitespace differences only (markdown wrapping), word-wise
    words = needle.split()
    pat = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pat, source_text)
    if not m:
        raise ValueError(f"quote not found verbatim in source: {needle[:120]!r}")
    return m.group(0)


# ------------------------------------------------------------------- run output
def write_output(source_key: str, rows: list[dict], rejects: list[dict]) -> Path:
    from scrapers.validate_raw import validate

    good, bad = [], list(rejects)
    for r in rows:
        errs = validate(r)
        if errs:
            bad.append({"row": r, "errors": errs})
        else:
            good.append(r)
    # determinism: dedupe identical ids keeping the richest row, then sort
    by_id: dict[str, dict] = {}
    for r in good:
        cur = by_id.get(r["id"])
        if cur is None:
            by_id[r["id"]] = r
            continue
        richer = (len(json.dumps(r)), r["as_of"]) > (len(json.dumps(cur)), cur["as_of"])
        if richer:
            # keep evidence union so nothing is lost
            merged_ev = cur["evidence"] + [e for e in r["evidence"] if e["url"] not in {x["url"] for x in cur["evidence"]}]
            by_id[r["id"]] = {**r, "evidence": merged_ev[:8]}
        else:
            cur["evidence"] = (cur["evidence"] + [e for e in r["evidence"] if e["url"] not in {x["url"] for x in cur["evidence"]}])[:8]
    out = sorted(by_id.values(), key=lambda r: (r["id"], r["as_of"]))
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{source_key}.jsonl"
    with p.open("w") as f:
        for r in out:
            f.write(json.dumps(r, sort_keys=False, ensure_ascii=False) + "\n")
    rj = OUT / f"{source_key}.rejects.json"
    rj.write_text(json.dumps(bad, indent=1)[:400_000])
    return p


def log_run(record: dict) -> None:
    p = ROOT / "scrapers" / "runs.jsonl"
    with p.open("a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def run_source(mod, *, offline: bool = False):
    """Execute one source module; write out/<key>.jsonl + runs.jsonl line."""
    t0 = time.time()
    http = Http(mod.SOURCE_KEY, offline=offline)
    rejects: list[dict] = []
    rows: list[dict] = []
    err = None
    try:
        rows, rejects = mod.fetch(http)
    except Exception as e:  # noqa: BLE001
        import traceback
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    p = write_output(mod.SOURCE_KEY, rows, rejects)
    n = sum(1 for _ in p.open()) if p.exists() else 0
    rec = {
        "source": mod.SOURCE_KEY, "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "as_of": AS_OF, "rows_in": len(rows), "rows_out": n, "rejects": len(rejects),
        "http_status_counts": http.status_counts, "errors": http.errors[:40],
        "error": err, "duration_s": round(time.time() - t0, 2),
        "offline": offline,
    }
    log_run(rec)
    return rec


# ------------------------------------------------------------------ taxonomy io
def load_taxonomy_aliases() -> dict[str, str]:
    """alias -> canonical family, from data/taxonomy.json (+ our extensions file)."""
    m: dict[str, str] = {}
    for fam in TAXONOMY["models"]:
        m[fam["family"]] = fam["family"]
        for a in fam.get("aliases", []):
            m[slugify(a)] = fam["family"]
    ext = ROOT / "data" / "taxonomy.extensions.json"
    if ext.exists():
        try:
            d = json.loads(ext.read_text())
            for fam in d.get("models", []):
                m[fam["family"]] = fam["family"]
                for a in fam.get("aliases", []):
                    m[slugify(a)] = fam["family"]
        except Exception:
            pass
    return m


def merge_extensions(models: dict[str, dict], hw_archs: dict[str, list[str]]) -> None:
    """Merge new model families / hw arch values into data/taxonomy.extensions.json."""
    p = ROOT / "data" / "taxonomy.extensions.json"
    cur = {"models": [], "hw_archs": {}}
    if p.exists():
        try:
            cur = json.loads(p.read_text())
        except Exception:
            pass
    have = {m["family"] for m in cur.get("models", [])}
    for fam, meta in sorted(models.items()):
        if fam in have:
            continue
        cur["models"].append({"family": fam, **meta})
    for vendor, archs in hw_archs.items():
        lst = cur.setdefault("hw_archs", {}).setdefault(vendor, [])
        for a in archs:
            if a not in lst:
                lst.append(a)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=2, ensure_ascii=False) + "\n")
