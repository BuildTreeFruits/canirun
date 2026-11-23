"""canirun combo-index — read/write store.

Standard library only. This module owns:

  * loading the export (data/combos.json, falling back to data/rows/*.jsonl)
  * CONTRACT.md §4 query matching + the miss payload (implemented key-for-key)
  * the vote store (data/votes.json), atomic, lock-guarded, idempotent per voter
  * the miss log (data/misses.jsonl) and auto-wanted promotion at 3 distinct searchers

Design notes
------------
The export on disk is the source of truth for *rows*. Votes are applied on top of
it at read time (an overlay) so that a vote never has to wait for a pipeline rebuild,
and so the pipeline can fold data/votes.json whenever it runs. If the export is
missing or unreadable the store degrades to an empty dataset and answers with a
well-formed miss plus `dataset.error` — an empty array alone is a bug (CONTRACT §4).

Nothing here imports the web framework; server.py is a thin HTTP shell over this.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
import threading
import time

# --------------------------------------------------------------------------
# constants mirrored from CONTRACT.md — do not change without messaging lead
# --------------------------------------------------------------------------

STATUSES = ("solved", "wanted", "rejected")
SOURCE_KINDS = ("scraped", "derived", "hand", "author-claim")
HW_VENDORS = ("nvidia", "amd", "intel", "apple", "qualcomm", "arm-cpu", "x86-cpu", "other")
MISS_REASONS = ("no-claim", "wanted-only", "rejected-only", "partial-context", "no-match")

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

# Auto-create a provisional wanted row once this many *distinct* searchers miss the
# same combination (blueprint §Open decisions, CONTRACT task brief).
CREATES_WANTED_AT = 3

QUERY_KEYS = ("hw", "model", "runtime", "status", "kind", "q", "limit")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLUG_SEP_RE = re.compile(r"[\s_]+")


def _today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_token(s: str) -> str:
    """Loose comparison form: lowercase, dots/underscores/spaces collapsed to '-'."""
    s = (s or "").strip().lower()
    s = _SLUG_SEP_RE.sub("-", s)
    s = re.sub(r"-+", "-", s)
    return s


def _rt_key(token: str) -> str:
    """Comparison key that treats `llama.cpp`, `llama_cpp` and `LLAMA.CPP` as one runtime.

    norm_token() already lowercases and collapses whitespace; this additionally folds
    the separator difference, which is the one CONTRACT §2 forces on us.
    """
    return token.replace("_", ".").replace("-", ".")


def runtime_alias_map(taxonomy: dict) -> dict[str, str]:
    """{flattened-id-form: canonical taxonomy slug}, e.g. {"llama_cpp": "llama.cpp"}.

    Exposed so /api/taxonomy and the docs can show both spellings, and so the UI can
    translate an id segment back to the slug it displays.
    """
    out = {}
    for rt in taxonomy.get("runtimes") or taxonomy.get("runtime") or []:
        if isinstance(rt, dict) and rt.get("slug"):
            slug = str(rt["slug"])
            out[slug.replace(".", "_")] = slug
    return out


def atomic_write_json(path: str, obj) -> None:
    """tmp file + os.replace — a crash never leaves a half-written votes.json."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def append_jsonl(path: str, obj) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_jsonl(path: str) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue  # a torn final line from a crash must not kill the log
                if isinstance(obj, dict):
                    out.append(obj)
    except FileNotFoundError:
        pass
    return out


def query_id_for(query: dict) -> str:
    """Stable 8-hex id for a normalised query — same query, same id, across processes."""
    canon = {k: query.get(k) for k in QUERY_KEYS}
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def parse_query(params) -> dict:
    """Normalise HTTP query params into the CONTRACT §4 `query` object.

    Accepts a dict of str->str, a dict of str->list[str], or a urllib parse_qs dict.
    Unknown params are ignored; empty strings become null.
    """

    def one(*names):
        for n in names:
            v = params.get(n)
            if isinstance(v, (list, tuple)):
                v = v[0] if v else None
            if v is None:
                continue
            if isinstance(v, str):
                v = v.strip()
                if not v:
                    continue
            return v
        return None

    limit_raw = one("limit")
    limit = DEFAULT_LIMIT
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
    limit = max(1, min(MAX_LIMIT, limit))

    return {
        "hw": one("hw"),
        "model": one("model"),
        "runtime": one("runtime"),
        "status": one("status"),
        "kind": one("kind", "source_kind"),
        "q": one("q"),
        "limit": limit,
    }


def _is_star(row: dict) -> bool:
    return row.get("model_family") == "*"


def _has_text(row: dict, needle: str) -> bool:
    hay = " ".join(
        str(row.get(k) or "")
        for k in ("id", "hw_vendor", "hw_arch", "hw_name", "model_family", "model_rev",
                  "runtime", "runtime_rev", "quant", "notes", "status", "source_kind")
    ).lower()
    if needle in hay:
        return True
    for ev in row.get("evidence") or []:
        if isinstance(ev, dict):
            if needle in str(ev.get("quote") or "").lower():
                return True
            if needle in str(ev.get("url") or "").lower():
                return True
    return False




def recaniruntime_segment(segment: str, taxonomy: dict) -> tuple[str | None, list[str]]:
    """Map a 4th id segment back to a taxonomy runtime slug.

    Ids may not contain dots (CONTRACT §2), so `llama.cpp` arrives as `llama_cpp`.
    Rules, in order:
      1. exact taxonomy slug match                       -> that slug
      2. slug with '.'->'_' equal to the segment         -> that slug
      3. segment already an exact slug of a dot-free
         runtime (`vllm`, `mlx-lm`)                      -> handled by rule 1
      4. anything else                                   -> (None, known slugs)
    Ambiguity (two taxonomy slugs collapsing to the same segment) is never guessed:
    the segment is returned unchanged so no row is invented from a coin flip.
    """
    seg = str(segment or "").strip()
    if not seg:
        return None, []
    slugs = []
    for rt in taxonomy.get("runtimes") or taxonomy.get("runtime") or []:
        if isinstance(rt, dict) and rt.get("slug"):
            slugs.append(str(rt["slug"]))
    if not slugs:
        return seg, []                      # no taxonomy: nothing to validate against

    if seg in slugs:                        # exact
        return seg, slugs
    collapsed = [s for s in slugs if s.replace(".", "_") == seg]
    if len(collapsed) == 1:                 # unambiguous dot-collapse
        return collapsed[0], slugs
    if len(collapsed) > 1:                  # ambiguous -> do not guess
        return seg, slugs
    return None, slugs                      # unknown runtime


def canonical_vote_id(row_id: str, taxonomy: dict) -> tuple[str, str | None, list[str], str | None]:
    """Normalise a vote id so the row the pipeline builds carries the right runtime.

    Returns (stored_id, canonical_runtime_slug, known_slugs, id_segment).

    The pipeline materialises a vote-only row with `runtime` = the id's 4th segment,
    so the segment must be the one the pipeline itself would derive for that runtime
    (``schema.runtime_id_segment``: `llama.cpp` -> `llama_cpp`). We therefore re-write
    the segment from the resolved slug — accepting either spelling from the caller while
    storing exactly one. Unknown runtimes give ``None`` for the slug and the id is
    returned untouched for the caller to reject.
    """
    parts = str(row_id).split("/")
    if len(parts) not in (4, 5):
        return row_id, None, [], None
    if len(parts) == 5 and not _VARIANT_SLUG_RE.match(parts[4]):
        return row_id, None, [], None
    slug, known = recaniruntime_segment(parts[3], taxonomy)
    if slug is None:
        return row_id, None, known, None

    segment = slug.replace(".", "_")          # fallback: CONTRACT §2 dot-flattening
    schema = _schema_module()
    if schema is not None:
        try:
            segment = schema.runtime_id_segment(slug)
        except Exception:  # noqa: BLE001 — fall back to the plain flattening
            pass
    tail = [segment, parts[4]] if len(parts) == 5 else [segment]
    stored = "/".join(parts[:3] + tail)
    return stored, slug, known, segment


# --------------------------------------------------------------------------
# id validation -- delegate to pipeline/schema.py, fall back to a local check
# --------------------------------------------------------------------------

_PIPELINE_SCHEMA = None
_PIPELINE_SCHEMA_ERR = None


def _schema_module():
    """Import pipeline.schema lazily (it may not exist on a fresh checkout)."""
    global _PIPELINE_SCHEMA, _PIPELINE_SCHEMA_ERR
    if _PIPELINE_SCHEMA is not None or _PIPELINE_SCHEMA_ERR is not None:
        return _PIPELINE_SCHEMA
    root = pipeline_root()
    try:
        if root not in sys.path:
            sys.path.insert(0, root)
        from pipeline import schema as _schema  # noqa: PLC0415
        _PIPELINE_SCHEMA = _schema
    except Exception as exc:  # noqa: BLE001 — a missing pipeline must not break voting
        _PIPELINE_SCHEMA_ERR = f"{type(exc).__name__}: {exc}"
    return _PIPELINE_SCHEMA


_LOCAL_ID_SEG = re.compile(r"^[a-z0-9*][a-z0-9_.-]*$")
_VARIANT_SLUG_RE = re.compile(r"^@[a-z0-9][a-z0-9_-]*$")


def compact_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def validate_row_id(row_id: str) -> tuple[bool, str, dict | None]:
    """Is `row_id` a legal CONTRACT §2 id (4-segment base or 5-segment /@slug variant)?
    Returns (ok, reason, segments).
    """
    if not isinstance(row_id, str) or not row_id or len(row_id) > 300:
        return False, "id missing, not a string, or absurdly long", None

    parts = row_id.split("/")
    if len(parts) not in (4, 5):
        return False, "id must be <hw_vendor>/<hw_arch>/<model_family>/<runtime>[/@slug]", None
    if len(parts) == 5 and not _VARIANT_SLUG_RE.match(parts[4]):
        return False, f"variant slug {parts[4]!r} must match ^@[a-z0-9][a-z0-9_-]*$", None

    base_id = "/".join(parts[:4])
    schema = _schema_module()
    if schema is not None:
        try:
            seg = schema.parse_id(base_id)               # raises IdError if not 4 segments
            roundtrip = schema.derive_id(seg["hw_vendor"], seg["hw_arch"],
                                         seg["model_family"], seg["runtime"])
        except Exception as exc:  # noqa: BLE001 — IdError/ValueError both mean "bad id"
            return False, str(exc) or type(exc).__name__, None
        if roundtrip != base_id:
            return False, (f"id is not canonical: {base_id!r} would be stored as "
                           f"{roundtrip!r} (lowercase, dots flattened to '_')"), None
        if len(parts) == 5:
            seg = dict(seg)
            seg["variant_slug"] = parts[4]
        return True, "", seg

    # Fallback when pipeline/schema.py is absent: local shape check only.
    for part in parts[:4]:
        if not _LOCAL_ID_SEG.match(part) or "." in part:
            return False, f"id segment {part!r} is not lowercase dot-free [a-z0-9_-]", None
    vendor, arch, family, runtime = parts[:4]
    seg = {"hw_vendor": vendor, "hw_arch": arch, "model_family": family, "runtime": runtime}
    if len(parts) == 5:
        seg["variant_slug"] = parts[4]
    return True, "", seg


# --------------------------------------------------------------------------
# dataset
# --------------------------------------------------------------------------

class Dataset:
    """An immutable snapshot of the rows, plus the taxonomy used for runtime labels."""

    __slots__ = ("rows", "version", "generated_at", "as_of", "error", "source",
                 "taxonomy", "_runtime_labels", "_runtime_collapsed", "_hw_vendors",
                 "_hw_alias_map", "_model_alias_map", "_row_by_id",
                 "wanted_override")

    def __init__(self, rows, version=None, generated_at=None, as_of=None,
                 error=None, source="none", taxonomy=None, wanted_override=None):
        self.rows = rows
        self.version = version
        self.generated_at = generated_at
        self.as_of = as_of
        self.error = error
        self.source = source
        self.taxonomy = taxonomy or {}
        # id -> explicit wanted record from /api/want, so a row absent from the export
        # still answers honestly instead of vanishing from /api/wanted.
        self.wanted_override = wanted_override or {}
        self._runtime_labels = {}
        # Dot-collapse map: ids may not contain '.', so a materialised vote row carries
        # the flattened segment (`llama_cpp`) while the taxonomy slug is `llama.cpp`.
        # Both forms must resolve to the same runtime for filtering and display.
        self._runtime_collapsed: dict[str, str] = {}
        for rt in self.taxonomy.get("runtimes") or self.taxonomy.get("runtime") or []:
            if isinstance(rt, dict) and rt.get("slug"):
                slug = norm_token(rt["slug"])
                self._runtime_labels[slug] = norm_token(rt.get("label") or "")
                self._runtime_collapsed[_rt_key(slug.replace(".", "_"))] = slug
        self._runtime_collapsed[_rt_key("unknown")] = "unknown"
        self._hw_vendors = set()
        for k in (self.taxonomy.get("hw_vendors") or {}):
            self._hw_vendors.add(norm_token(k))
        self._hw_alias_map: dict[str, str] = {}
        for k, v in (self.taxonomy.get("hw_aliases") or {}).items():
            if k and v:
                canon = norm_token(v)
                self._hw_alias_map[norm_token(k)] = canon
                self._hw_alias_map[compact_token(k)] = canon
        self._model_alias_map: dict[str, str] = {}
        for m in (self.taxonomy.get("models") or []):
            if not isinstance(m, dict) or not m.get("family"):
                continue
            fam = norm_token(m["family"])
            self._model_alias_map[fam] = fam
            self._model_alias_map[compact_token(fam)] = fam
            for a in (m.get("aliases") or []):
                if a:
                    self._model_alias_map[norm_token(a)] = fam
                    self._model_alias_map[compact_token(a)] = fam
        self._row_by_id: dict[str, dict] = {
            str(r["id"]): r for r in self.rows if r.get("id")
        }

    # -- derived -----------------------------------------------------------

    def counts(self) -> dict:
        by_status: dict[str, int] = {}
        by_vendor: dict[str, int] = {}
        by_runtime: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for r in self.rows:
            for bucket, key in ((by_status, "status"), (by_vendor, "hw_vendor"),
                                (by_runtime, "runtime"), (by_kind, "source_kind")):
                v = str(r.get(key) or "?")
                bucket[v] = bucket.get(v, 0) + 1
        return {"rows": len(self.rows), "by_status": by_status, "by_vendor": by_vendor,
                "by_runtime": by_runtime, "by_source_kind": by_kind}

    def meta(self) -> dict:
        as_of = self.as_of
        if not as_of:
            dates = sorted(r.get("as_of") for r in self.rows if _DATE_RE.match(str(r.get("as_of") or "")))
            as_of = dates[-1] if dates else None
        return {"rows": len(self.rows), "as_of": as_of, "version": self.version}

    # -- matching ----------------------------------------------------------

    def match_hw(self, row: dict, hw: str) -> bool:
        """CONTRACT §4: hw_arch exactly, else hw_vendor exactly, else prefix."""
        want = norm_token(hw)
        canon = self._hw_alias_map.get(want) or self._hw_alias_map.get(compact_token(hw))
        candidates = [want] + ([canon] if canon and canon != want else [])
        arch = norm_token(row.get("hw_arch") or "")
        vendor = norm_token(row.get("hw_vendor") or "")
        name = norm_token(row.get("hw_name") or "")
        for c in candidates:
            if arch == c or vendor == c:
                return True
            if arch.startswith(c) or vendor.startswith(c):
                return True
            if name and c in name:
                return True
        return False

    def match_model(self, row: dict, model: str) -> bool:
        """CONTRACT §4: model_family exactly, else contains. Returns True for `*` rows
        only when the caller asked for a specific model (they are context, never an answer)."""
        want = norm_token(model)
        canon = self._model_alias_map.get(want) or self._model_alias_map.get(compact_token(model))
        candidates = [want] + ([canon] if canon and canon != want else [])
        fam = norm_token(row.get("model_family") or "")
        for c in candidates:
            if fam == c:
                return True
            if c and fam and (c in fam or fam in c):
                return True
        return False

    def canonical_runtime(self, value: str) -> str:
        """Accept both taxonomy form (`llama.cpp`) and id form (`llama_cpp`).

        pipeline/votes.py materialises a vote-only row with `runtime` = the id segment,
        and ids may not contain dots (CONTRACT §2). Without this, `?runtime=llama.cpp`
        returns a miss for a row that plainly exists -- an agent-visible false negative.
        """
        tok = norm_token(value)
        return self._runtime_collapsed.get(_rt_key(tok), tok)

    def match_runtime(self, row: dict, runtime: str) -> bool:
        """CONTRACT §4: slug (either spelling), then display name."""
        want = self.canonical_runtime(runtime)
        slug = self.canonical_runtime(row.get("runtime") or "")
        if slug and slug == want:
            return True
        for key in (norm_token(row.get("runtime") or ""), slug):
            label = self._runtime_labels.get(key) or ""
            if label and (label == want or (want and want in label)):
                return True
        return False

    def matches(self, row: dict, q: dict, *, include_status: bool = True) -> bool:
        if q.get("hw") and not self.match_hw(row, q["hw"]):
            return False
        if q.get("runtime") and not self.match_runtime(row, q["runtime"]):
            return False
        if q.get("model") and not _is_star(row) and not self.match_model(row, q["model"]):
            return False
        if include_status and q.get("status") and row.get("status") != q["status"]:
            return False
        if q.get("kind") and row.get("source_kind") != q["kind"]:
            return False
        if q.get("q") and not _has_text(row, q["q"].lower()):
            return False
        return True

    def search(self, q: dict) -> dict:
        """The CONTRACT §4 response body (votes are applied by the caller/engine)."""
        limit = q.get("limit") or DEFAULT_LIMIT
        answers: list[dict] = []
        context: list[dict] = []
        stars: list[dict] = []

        ask_model = bool(q.get("model"))

        for row in self.rows:
            if not self.matches(row, q, include_status=False):
                continue
            if _is_star(row):
                stars.append(row)
            else:
                answers.append(row)

        # A query with no model asked for hardware-level facts too: `*` rows are
        # legitimate answers then (they are not answering a model question). With a
        # model asked, they stay in `context` and never count as an answer (§3).
        if not ask_model:
            answers.extend(stars)

        # status filter is applied to answer rows, but the *reason* for a miss needs
        # to know what existed before filtering -> compute both views.
        if q.get("status"):
            answers = [r for r in answers if r.get("status") == q["status"]]

        # wanted rows sort first (votes desc), then solved, then rejected; within
        # a status, most-recent as_of first, then id for determinism.
        answers.sort(key=_sort_key)

        rows_out = []
        for r in answers[:limit]:
            pid = r.get("parent")
            if pid and (self._row_by_id.get(str(pid)) or {}).get("status") == "untested":
                r = dict(r)
                r["parent_untested"] = True
            rows_out.append(r)
        # `*` rows are `context` only when a model was asked -- otherwise they were
        # promoted into `rows` above and listing them again would double-count them.
        context_out = ([] if not ask_model else stars)[:limit]
        miss = self._miss(q, answers, stars)
        return {"query": q, "rows": rows_out, "context": context_out, "miss": miss}

    def _miss(self, q: dict, answers: list[dict], stars: list[dict]) -> dict:
        is_miss = len(answers) == 0
        if not is_miss:
            return {"is_miss": False}

        # Which statuses *would* have matched, to name the reason honestly.
        unfiltered = [r for r in self.rows if self.matches(r, q, include_status=False)
                      and not _is_star(r)]
        statuses = {r.get("status") for r in unfiltered}
        if not unfiltered and not stars:
            reason = "no-match"
        elif unfiltered and statuses == {"untested"}:
            reason = "untested-only"
        elif unfiltered and statuses == {"rejected"}:
            reason = "rejected-only"
        elif not unfiltered and stars:
            reason = "partial-context"
        else:
            reason = "no-match"

        # untested rows that match this query (for vote counts / basis)
        untested = [r for r in unfiltered if r.get("status") == "untested"]
        wanted_votes = max((r.get("want_votes") or 0) for r in untested) if untested else 0
        untested_basis = sorted({str(r["basis"]) for r in untested if r.get("basis")})
        last_checked = None
        dated = sorted(str(r.get("as_of")) for r in (unfiltered or stars) if _DATE_RE.match(str(r.get("as_of") or "")))
        if dated:
            last_checked = dated[-1]

        return {
            "is_miss": True,
            "reason": reason,
            "partial": bool(stars),
            "hint": self._hint(q, reason, stars, wanted_votes, untested_basis),
            "known_untested": bool(untested),
            "known_wanted": bool(untested),
            "wanted_votes": wanted_votes,
            "untested_basis": untested_basis,
            "last_checked": last_checked,
            "counts": {"exact": 0, "context": len(stars)},
        }

    def _hint(self, q: dict, reason: str, stars: list[dict], wanted_votes: int,
              untested_basis: list[str] | None = None) -> str:
        def label() -> str:
            parts = []
            if q.get("hw"):
                parts.append(str(q["hw"]))
            if q.get("model"):
                parts.append(str(q["model"]))
            if q.get("runtime"):
                parts.append(str(q["runtime"]))
            return " × ".join(parts) if parts else "this query"

        where = label()
        if reason == "no-match":
            return f"No claim on record for {where}, and no hardware-level rows match either. This is a recorded gap, not a broken page."
        if reason == "partial-context":
            rts = sorted({str(s.get("runtime")) for s in stars if s.get("runtime")})
            tail = f" Hardware-level support exists for {', '.join(rts)}; no model-specific claim." if rts else ""
            return f"No claim on record for {where}.{tail}"
        if reason == "untested-only":
            if untested_basis:
                return (f"Proposed, unverified claim on record for {where} "
                        f"(basis: {', '.join(untested_basis)}; {wanted_votes} want vote(s)). "
                        "Do not treat as verified fact — check the basis note or verify before relying on it.")
            return (f"Proposed, unverified gap on record for {where} "
                    f"({wanted_votes} want vote(s), no basis claim yet). "
                    "Vote to raise it, or submit a verified pointer.")
        if reason == "rejected-only":
            return (f"No solved claim on record for {where}; what is on record is a rejection. "
                    "Read the rejection notes before trying — that is why it fails on this card.")
        return f"No claim on record for {where}."


def _sort_key(row: dict):
    status = str(row.get("status"))
    status_rank = {"untested": 0, "solved": 1, "rejected": 2}.get(status, 3)
    basis_rank = 0 if (status == "untested" and row.get("basis")) else (1 if status == "untested" else 0)
    votes = row.get("want_votes") or 0
    return (status_rank, basis_rank, -votes, _neg_date(row.get("as_of")), str(row.get("id") or ""))


def _neg_date(d) -> str:
    """Sortable key that puts the newest date first without arithmetic on strings."""
    s = str(d or "")
    if not _DATE_RE.match(s):
        return "\uffff"
    # invert digits so reverse-lexicographic works with a plain sort
    return "".join(chr(ord("9") - (ord(c) - ord("0"))) if c.isdigit() else c for c in s)


# --------------------------------------------------------------------------
# votes + misses (the write path)
# --------------------------------------------------------------------------

class Store:
    def __init__(self, data_dir: str, *, sync_rebuild: bool = False):
        self.data_dir = os.path.abspath(data_dir)
        self._lock = threading.RLock()
        self._cache: Dataset | None = None
        self._cache_sig = None
        self._rebuild_lock = threading.Lock()
        self._rebuild_running = False
        self._rebuild_pending = False
        self.sync_rebuild = sync_rebuild
        self.errors: list[str] = []  # recent write-path failures, surfaced on /api/health

        self.rows_dir = os.path.join(self.data_dir, "rows")
        self.combos_path = os.path.join(self.data_dir, "combos.json")
        self.export_jsonl_path = os.path.join(self.data_dir, "export.jsonl")
        self.votes_path = os.path.join(self.data_dir, "votes.json")
        self.misses_path = os.path.join(self.data_dir, "misses.jsonl")
        self.taxonomy_path = os.path.join(self.data_dir, "taxonomy.json")

    # -- taxonomy ----------------------------------------------------------

    def taxonomy(self) -> dict:
        try:
            with open(self.taxonomy_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    # -- dataset loading ---------------------------------------------------

    def _signature(self):
        sig = []
        for p in (self.combos_path, self.misses_path, self.votes_path):
            try:
                st = os.stat(p)
                sig.append((p, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((p, None, None))
        try:
            if os.path.isdir(self.rows_dir):
                names = sorted(os.listdir(self.rows_dir))
                sig.append(("rows", tuple(names), os.stat(self.rows_dir).st_mtime_ns))
        except OSError:
            pass
        return tuple(sig)

    def dataset(self, *, force: bool = False) -> Dataset:
        sig = self._signature()
        with self._lock:
            if not force and self._cache is not None and sig == self._cache_sig:
                return self._cache
        ds = self._load()
        with self._lock:
            self._cache, self._cache_sig = ds, sig
            return ds

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None
            self._cache_sig = None

    def schedule_rebuild(self, *, sync: bool | None = None) -> dict:
        """Schedule a non-blocking, coalescing pipeline rebuild on a background thread.

        At most one rebuild runs at a time; triggers arriving mid-rebuild coalesce into
        a single follow-up run. Pass sync=True in tests that need immediate completion.
        """
        if sync is None:
            sync = self.sync_rebuild
        if sync:
            ok, detail = try_pipeline_rebuild(self.data_dir)
            if not ok:
                self.errors.append({"ts": _utcnow(), "what": "pipeline_rebuild",
                                    "detail": detail})
            self.invalidate()
            return {"scheduled": False, "ok": ok, "detail": detail}

        with self._rebuild_lock:
            if self._rebuild_running:
                self._rebuild_pending = True
                self.invalidate()
                return {"scheduled": True, "coalesced": True}
            self._rebuild_running = True
            self._rebuild_pending = False

        self.invalidate()

        def _worker() -> None:
            while True:
                try:
                    ok, detail = try_pipeline_rebuild(self.data_dir)
                    if not ok:
                        self.errors.append({"ts": _utcnow(), "what": "pipeline_rebuild",
                                            "detail": detail})
                    self.invalidate()
                finally:
                    with self._rebuild_lock:
                        if self._rebuild_pending:
                            self._rebuild_pending = False
                            continue
                        self._rebuild_running = False
                        break

        threading.Thread(target=_worker, name="store-rebuild", daemon=True).start()
        return {"scheduled": True}

    def _load(self) -> Dataset:
        taxonomy = self.taxonomy()
        # 1) the export — the canonical, pre-joined file
        try:
            with open(self.combos_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            if isinstance(blob, dict) and isinstance(blob.get("rows"), list):
                ds = Dataset(
                    [r for r in blob["rows"] if isinstance(r, dict)],
                    version=blob.get("version"),
                    generated_at=blob.get("generated_at"),
                    as_of=blob.get("as_of"),
                    source="combos.json",
                    taxonomy=blob.get("taxonomy") or taxonomy,
                )
                return self._apply_wanted(ds)
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            # corrupt export: keep serving from the rows store rather than 500
            err = f"combos.json unreadable ({type(exc).__name__}: {exc}); serving data/rows/*.jsonl"
        else:
            err = "combos.json present but has no rows[]; serving data/rows/*.jsonl"

        # 2) fallback — assemble from the per-vendor JSONL store
        rows: list[dict] = []
        try:
            if os.path.isdir(self.rows_dir):
                for name in sorted(os.listdir(self.rows_dir)):
                    if name.endswith(".jsonl"):
                        rows.extend(read_jsonl(os.path.join(self.rows_dir, name)))
        except OSError as exc:
            err = f"data/rows unreadable: {exc}"
        if not rows and not os.path.exists(self.combos_path):
            err = ("no export yet: data/combos.json is missing. "
                   "Run `python3 pipeline/build.py` (or `python3 scripts/serve.py`, which builds it).")
        ds = Dataset(rows, source="rows", error=err, taxonomy=taxonomy)
        return self._apply_wanted(ds)

    def _apply_wanted(self, ds: Dataset) -> Dataset:
        """Overlay votes.json counts. CONTRACT §1: want_votes is authoritative, and a
        status=="wanted" row must carry want_votes>=1 + want_first — so a vote on a row
        the export has not folded in yet still gets applied here."""
        votes = self.votes()
        if not votes:
            return ds
        changed = False
        out = []
        for row in ds.rows:
            rec = votes.get(str(row.get("id")))
            if not rec:
                out.append(row)
                continue
            r = dict(row)
            count = int(rec.get("count") or 0)
            r["want_votes"] = count
            r["want_requesters"] = list(rec.get("requesters") or [])[:10]
            r["want_first"] = rec.get("first")
            if (row.get("status") in (None, "wanted", "untested") and count >= 1 and not row.get("pointer")):
                r["status"] = "untested"
            changed = True
            out.append(r)
        # votes for ids that are not in the export (row not built yet) stay addressable
        known = {str(r.get("id")) for r in out}
        override = {k: v for k, v in votes.items() if k not in known and (v.get("count") or 0) > 0}
        if not changed and override == ds.wanted_override:
            return ds
        return Dataset(out, version=ds.version, generated_at=ds.generated_at, as_of=ds.as_of,
                       error=ds.error, source=ds.source, taxonomy=ds.taxonomy,
                       wanted_override=override)

    # -- votes -------------------------------------------------------------

    def votes(self) -> dict:
        try:
            with open(self.votes_path, "r", encoding="utf-8") as fh:
                blob = json.load(fh)
            return blob if isinstance(blob, dict) else {}
        except (OSError, ValueError):
            return {}

    def row_by_id(self, row_id: str) -> dict | None:
        for r in self.dataset().rows:
            if str(r.get("id")) == row_id:
                return r
        return None

    def vote(self, row_id: str, voter: str, *, add: bool) -> dict:
        """Idempotent per (id, voter). Returns the CONTRACT-shaped vote result."""
        today = _today()
        with self._lock:
            votes = self.votes()
            rec = votes.get(row_id)
            if not isinstance(rec, dict):
                rec = {"count": 0, "requesters": [], "first": None}
            requesters = [str(x) for x in (rec.get("requesters") or [])]
            present = voter in requesters
            changed = False
            if add and not present:
                requesters.append(voter)
                rec["count"] = int(rec.get("count") or 0) + 1
                rec["first"] = rec.get("first") or today
                changed = True
            elif not add and present:
                requesters.remove(voter)
                rec["count"] = max(0, int(rec.get("count") or 0) - 1)
                if rec["count"] == 0:
                    rec["first"] = None
                changed = True
            # count is derived from the requester set — never a separate tally
            rec["requesters"] = requesters
            rec["count"] = len(requesters)
            if changed:
                votes[row_id] = rec
                atomic_write_json(self.votes_path, votes)
        self.invalidate()
        return {
            "id": row_id,
            "want_votes": rec["count"],
            "want_first": rec.get("first"),
            "voted": voter in requesters,
        }

    # -- misses ------------------------------------------------------------

    def log_miss(self, query: dict, searcher_key: str, user_agent: str = "",
                 query_id: str | None = None) -> dict:
        qid = query_id or query_id_for(query)
        key = str(searcher_key or "anon")
        with self._lock:
            append_jsonl(self.misses_path, {
                "ts": _utcnow(),
                "query": {k: query.get(k) for k in QUERY_KEYS if k != "limit"},
                "query_id": qid,
                "searcher_key": key,
                "user_agent": (user_agent or "")[:300],
            })
            distinct = self.distinct_searchers(qid)
        self.invalidate()
        return {
            "logged": True,
            "query_id": qid,
            "distinct_searchers": distinct,
            "creates_wanted_at": CREATES_WANTED_AT,
            "would_create_wanted": distinct >= CREATES_WANTED_AT,
        }

    def distinct_searchers(self, query_id: str) -> int:
        keys = set()
        for rec in read_jsonl(self.misses_path):
            if rec.get("query_id") == query_id:
                keys.add(str(rec.get("searcher_key") or "anon"))
        return len(keys)

    def miss_records(self, query_id: str | None = None) -> list[dict]:
        recs = read_jsonl(self.misses_path)
        if query_id:
            recs = [r for r in recs if r.get("query_id") == query_id]
        return recs

    # -- export ------------------------------------------------------------

    def export_bytes(self) -> tuple[bytes | None, str]:
        """The /api/export.jsonl payload + its ETag. Prefer the pipeline's own export;
        otherwise synthesise deterministic JSONL from the current (vote-overlaid) rows."""
        try:
            with open(self.export_jsonl_path, "rb") as fh:
                data = fh.read()
            if data.strip():
                return data, etag_for(data)
        except OSError:
            pass
        ds = self.dataset()
        if not ds.rows:
            return None, etag_for(b"")
        lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in ds.rows]
        data = ("\n".join(lines) + "\n").encode("utf-8")
        return data, etag_for(data)

    def combos_bytes(self) -> tuple[bytes | None, str, dict]:
        """The /api/combos.json payload + ETag + the envelope used for headers."""
        try:
            with open(self.combos_path, "rb") as fh:
                data = fh.read()
            blob = json.loads(data) if data.strip() else {}
            meta = {"version": blob.get("version"), "generated_at": blob.get("generated_at"),
                    "as_of": blob.get("as_of"), "rows": len(blob.get("rows") or [])}
            return data, etag_for(data), meta
        except (OSError, ValueError):
            pass
        ds = self.dataset()
        if not ds.rows:
            return None, etag_for(b""), ds.meta()
        blob = {
            "version": ds.version,
            "generated_at": ds.generated_at or _utcnow(),
            "as_of": ds.meta()["as_of"],
            "counts": ds.counts(),
            "taxonomy": ds.taxonomy,
            "rows": ds.rows,
            "wanted": [r for r in ds.rows if r.get("status") == "wanted"],
        }
        data = json.dumps(blob, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        return data, etag_for(data), ds.meta()


def etag_for(data: bytes) -> str:
    return '"' + hashlib.sha256(data).hexdigest()[:32] + '"'


# --------------------------------------------------------------------------
# pipeline hook — the write path may trigger a rebuild, and must survive it failing
# --------------------------------------------------------------------------

def pipeline_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_REBUILD_LOCK = threading.Lock()

def try_pipeline_rebuild(data_dir: str, timeout: float = 30.0) -> tuple[bool, str]:
    """Fold votes/misses into the export by calling the pipeline.

    Calls ``pipeline.build.build(util.paths(root), quiet=True)`` — the function API, not
    ``main()``: main() is an argparse CLI whose SystemExit would otherwise take the
    server down with it (observed: a 3-distinct-searcher miss killed the process).
    The call runs in a daemon thread with a timeout, is single-flight (a burst of votes
    stacks one rebuild, not N), and never raises: the read path must not die with the
    write path.
    """
    global _REBUILD_LOCK
    if _REBUILD_LOCK is None:
        _REBUILD_LOCK = threading.Lock()

    root = pipeline_root()
    build_py = os.path.join(root, "pipeline", "build.py")
    if not os.path.exists(build_py):
        return False, "pipeline/build.py not present yet"

    data_dir = os.path.abspath(data_dir)
    # A rebuild rewrites <root>/data/*, so only rebuild a dir laid out as <root>/data.
    # That keeps `--data-dir api/tests/tmp/...` from ever touching the live tree.
    use_root = os.path.dirname(data_dir) if os.path.basename(data_dir) == "data" else None
    if use_root is None:
        return False, f"skipped: {data_dir} is not <root>/data; refusing to rebuild a foreign tree"

    # Single-flight: if a rebuild is already running, do not queue a second one.
    if not _REBUILD_LOCK.acquire(blocking=False):
        return False, "skipped: a rebuild is already in flight"

    try:
        sys.path.insert(0, root) if root not in sys.path else None
        result: dict = {}

        def _run():
            try:
                from pipeline import build as build_mod  # noqa: PLC0415
                from pipeline import util as util_mod  # noqa: PLC0415
                fn = getattr(build_mod, "build", None)
                if fn is None:
                    result["err"] = "pipeline.build exposes no build() "
                    return
                fn(util_mod.paths(use_root), quiet=True)
                result["ok"] = True
            except BaseException as exc:  # noqa: BLE001 — incl. SystemExit from a CLI main()
                result["err"] = f"{type(exc).__name__}: {exc}"

        t = threading.Thread(target=_run, name="pipeline-rebuild", daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return False, f"timed out after {timeout}s; rebuild continues in the background"
        if result.get("ok"):
            return True, f"rebuilt {use_root}"
        err = result.get("err") or "unknown error"
        return False, err + " (see pipeline/schema.py rejection; the API still answers wanted rows from votes.json)"
    finally:
        _REBUILD_LOCK.release()
