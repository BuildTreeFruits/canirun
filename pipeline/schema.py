"""Canonical row schema for the solve.run combination index.

This module is the single source of truth for CONTRACT.md §1 (the row),
§2 (canonical id) and the row-level invariants.  It is deliberately
**dependency-free** (Python 3 stdlib only, no I/O at import time) so that
`api/` and `web`-side tooling can import it without pulling in the pipeline.

Public API
----------
ROWS_CONTRACT_VERSION   -- bump only when the stored row shape changes
now() / today()         -- UTC clock helpers used elsewhere in the pipeline
IdError, RowError       -- raised by derive_id / validate
derive_id(hw_vendor, hw_arch, model_family, runtime) -> str
slugify_arch, slugify_model, slugify_runtime, slugify_vendor
canonicalize(raw, *, source_key=None, today=None) -> dict
validate(row, *, taxonomy=None, today=None) -> list[str]
validate_errors(row, ...) -> dict[str, list[str]]
is_valid(row, ...) -> bool
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

ROWS_CONTRACT_VERSION = "1"

# ---------------------------------------------------------------------------
# Enumerations (CONTRACT §1)
# ---------------------------------------------------------------------------

STATUSES = ("solved", "wanted", "rejected")
SOURCE_KINDS = ("scraped", "derived", "hand", "author-claim")
CREATED_BY = ("scraper", "derived", "hand", "vote", "miss")
EVIDENCE_KINDS = ("upstream-doc", "package-table", "model-repo", "release", "issue", "community")

# Fallback only -- the live list comes from data/taxonomy.json hw_vendors.
HW_VENDORS = (
    "nvidia", "amd", "intel", "apple", "qualcomm", "arm-cpu", "x86-cpu", "other",
)

# CONTRACT §5: higher rank wins the base.
SOURCE_KIND_RANK = {"derived": 0, "scraped": 1, "hand": 2, "author-claim": 3}

BANNED_RUNTIME_REVS = frozenset({"latest", "master", "main", "head", ""})
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# CONTRACT §2: lowercase [a-z0-9], `_` and `-` allowed *inside* id segments,
# dots are not allowed in ids at all.
ID_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
ID_MODEL_SEGMENT_RE = re.compile(r"^([a-z0-9]+(?:[-_][a-z0-9]+)*|\*)$")
# A field value is a slug if it consists only of lowercase alnum plus '._-' and
# is not all punctuation; '.' is then the only character derive_id rewrites.
_SAFE_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$|^\*$")
_ID_SEGMENT_CHARS_RE = re.compile(r"^[a-z0-9_-]+$")
# model_family additionally allows dots (e.g. "qwen2.5") in the *field* form;
# the id segment flattens the dot to "_".
MODEL_FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$|^\*$")


class RowError(ValueError):
    """Raised when a row cannot even be canonicalised (hard, structural)."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


class IdError(ValueError):
    """Raised when an id cannot be derived from its component fields."""

    def __init__(self, errors=""):
        self.errors = errors if isinstance(errors, list) else [str(errors)]
        super().__init__("; ".join(self.errors))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def now() -> str:
    """UTC timestamp, second precision, Z suffix (stable, timezone-free)."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    """UTC calendar date, YYYY-MM-DD."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def parse_date(value: Any) -> Optional[str]:
    """Return the YYYY-MM-DD string if valid, else None."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        return None
    return value


# ---------------------------------------------------------------------------
# Slugs / id derivation (CONTRACT §2)
# ---------------------------------------------------------------------------

def _slugify(value: Any, *, allow_dot: bool = True, flatten_dot: bool = False) -> str:
    """Lowercase slug.  Runs of non [a-z0-9._-] collapse into a single '-'.

    allow_dot   -- keep '.' as an allowed character
    flatten_dot -- turn '.' into '_' (id segments: dots are NOT allowed)
    """
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = s.replace("_", "_")  # explicit: underscore is legal in ids
    out: List[str] = []
    for ch in s:
        if ch.isalnum() and ch.isascii():
            out.append(ch)
        elif ch == "-":
            out.append("-")
        elif ch == "_":
            out.append("_")
        elif ch == "." and allow_dot:
            out.append("_" if flatten_dot else ".")
        else:
            out.append("-")
    slug = "".join(out)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    slug = re.sub(r"_{2,}", "_", slug).strip("_")
    if flatten_dot:
        slug = slug.replace(".", "_")
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def slugify_vendor(value: Any) -> str:
    """hw_vendor is an enum slug: only [a-z0-9-]."""
    return _slugify(value, allow_dot=False).replace("_", "-")


def slugify_arch(value: Any) -> str:
    """hw_arch: `sm_86`, `gfx1100`, `arc-b580`.  Dots are flattened to '-'."""
    return _slugify(value, allow_dot=False)


def slugify_model(value: Any) -> str:
    """model_family field form.  `*` is preserved (CONTRACT §3).

    Dots are kept in the *field* (`qwen2.5`) but flattened in the id segment.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if s == "*":
        return "*"
    return _slugify(s, allow_dot=True)


def model_id_segment(model_family: Any) -> str:
    """The model_family as it appears in an id: dots -> '_' (CONTRACT §2)."""
    if model_family is None:
        return ""
    if str(model_family).strip() == "*":
        return "*"
    return _slugify(model_family, allow_dot=True, flatten_dot=True)


def slugify_runtime(value: Any) -> str:
    """runtime slug from taxonomy: `llama.cpp`, `mlx-lm`, `vllm-metal`."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    # runtime slugs keep '.' (llama.cpp) but the id may not -- ids flatten it.
    return _slugify(s, allow_dot=True)


def runtime_id_segment(runtime: Any) -> str:
    return _slugify(runtime, allow_dot=True, flatten_dot=True)


def derive_id(hw_vendor: Any, hw_arch: Any, model_family: Any, runtime: Any) -> str:
    """CONTRACT §2 (normative, "the one rule, stated once"):

        id = f"{hw_vendor}/{hw_arch}/{model_family_id}/{runtime_id}"

    1. each segment is lowercased;
    2. every '.' inside a segment becomes '_'  -- this is the *only* transform;
    3. '_' and '-' pass through unchanged; no other character is rewritten.

    The fields themselves are never rewritten: ``runtime`` keeps its taxonomy
    slug (``llama.cpp``), ``model_family`` keeps its dots (``qwen2.5``); only
    the id loses them.  So:

        nvidia/sm_86/qwen2_5/llama_cpp, apple/m4_pro/*/mlx_lm,
        other/ascend-910b/llama-3/llama_cpp

    Raises IdError for input that is not a clean slug (a space, stray
    punctuation, or anything else rule 3 does not pass through): callers must
    not be handed a silently-repaired id.
    """
    fields = (hw_vendor, hw_arch, model_family, runtime)
    labels = ("hw_vendor", "hw_arch", "model_family", "runtime")
    errors: List[str] = []
    segs: List[str] = []
    for label, value in zip(labels, fields):
        if value is None or not str(value).strip():
            errors.append(f"id: empty segment for {label!r}")
            segs.append("")
            continue
        raw = str(value).strip()
        if raw != "*" and not _SAFE_SEGMENT_RE.match(raw.lower()):
            errors.append(f"id: {label} {raw!r} is not a slug (lowercase [a-z0-9._-], "
                          f"the only transform is '.' -> '_')")
        if raw == "*":
            if label != "model_family":
                errors.append("id: '*' is only valid as a model_family")
            segs.append("*")
            continue
        segs.append(raw.lower().replace(".", "_"))
    # Rule 3 passes '_' and '-' through unchanged: a segment like `mlx_lm` or
    # `llama-3_1` is legal even though it mixes the two separators.
    if not errors:
        for label, seg in zip(labels, segs):
            if seg in ("", "*"):
                continue
            if not _ID_SEGMENT_CHARS_RE.match(seg):
                errors.append(f"id: segment {seg!r} ({label}) is not a valid id slug")
    if errors:
        raise IdError(errors)
    return "/".join(segs)


def parse_id(row_id: Any) -> Dict[str, str]:
    """Inverse of derive_id (approximate: dotted segments are not recoverable)."""
    if not isinstance(row_id, str) or row_id.count("/") != 3:
        raise IdError([f"id: {row_id!r} is not of the form vendor/arch/model/runtime"])
    vendor, arch, model, runtime = row_id.split("/")
    return {"hw_vendor": vendor, "hw_arch": arch, "model_family": model, "runtime": runtime}


# ---------------------------------------------------------------------------
# Canonicalisation: scraper emit -> stored row
# ---------------------------------------------------------------------------

# Scrapers emit the CONTRACT fields; a few convenience aliases are accepted so
# a scraper bug is fixable rather than fatal, but nothing is invented.
_ALIASES = {
    "hw": "hw_arch",
    "arch": "hw_arch",
    "gpu_arch": "hw_arch",
    "model": "model_family",
    "family": "model_family",
    "engine": "runtime",
    "source": "reported_by",
    "url": "pointer",
}

_KNOWN_FIELDS = (
    "id", "status", "source_kind", "provisional",
    "hw_vendor", "hw_arch", "hw_name", "hw_extra",
    "model_family", "model_rev", "quant",
    "runtime", "runtime_rev",
    "pointer", "notes", "measurement", "pointer_alive",
    "as_of", "reported_by", "first_seen", "updated",
    "want_votes", "want_first", "want_requesters",
    "evidence", "missing", "created_by", "sources", "vocabulary", "missing_fixed",
    "resolves_no_claim", "miss_reports", "markers_complete",
)

_EMPTY_STRINGS = frozenset({"", "null", "none", "n/a", "na", "unknown", "-", "?????"})

# A missing marker inferring *model-level* information that the scraper
# flagged as "hw" *cannot* under CONTRACT invariant 2: scraped rows must be
# complete.  enumerate_missing() upgrades these in canonicalize(); the action is
# recorded in row["missing_fixed"] so the correction is auditable, not silent.
_UPGRADEABLE = frozenset({"hw", "hardware", "gpu", "hw_vendor", "hw_arch", "card", "model", "runtime"})


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in _EMPTY_STRINGS:
        return None
    return s


def _clean_list(value: Any, *, upper: bool = False) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    out: List[str] = []
    seen = set()
    for item in items:
        s = _clean_str(item)
        if s is None:
            continue
        s = s.lower() if upper else s
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _parse_date_loose(value: Any) -> Optional[str]:
    """Return value if it is a valid YYYY-MM-DD, else None (validator reports)."""
    return parse_date(value) if isinstance(value, str) else None


def _norm_evidence(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return [value] if isinstance(value, dict) else []
    out: List[Dict[str, str]] = []
    seen = set()
    for ev in value:
        if not isinstance(ev, Mapping):
            out.append({"__bad__": repr(ev)})  # validator will flag it
            continue
        url = _clean_str(ev.get("url"))
        quote = _clean_str(ev.get("quote"))
        kind = _clean_str(ev.get("kind"))
        key = url or repr(ev)
        if key in seen:
            continue
        seen.add(key)
        out.append({"url": url, "quote": quote, "kind": kind})
    return out


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y", "alive"):
            return True
        if v in ("false", "0", "no", "n", "dead"):
            return False
    return default


def enumerate_missing(missing: Iterable[str]) -> List[str]:
    """Return `missing` normalised so it reports *model-level* gaps.

    CONTRACT treats three different gaps:
      * missing "model"    -- hardware × runtime claim, no model ("*" rows, §3)
      * missing "hw"       -- a model × runtime artifact with no hardware claim
      * missing []         -- nothing missing; the row is a complete claim

    Rules (CONTRACT §1 inv 2/3/9):
      * a row that names {hw, model} is a complete join -> [] (unless derived,
        see canonicalize: a derived row always keeps a marker);
      * a row that lacks model-level information (``hw`` only) states both
        ``model`` and the dimension it lacks;
      * a ``*`` row always carries ``model`` (inv 9).
    """
    tags = _clean_list(missing)
    if not tags:
        return []
    has_model = "model" in tags
    has_hw = "hw" in tags
    # A row that already names a dimension is not "missing" it: {hw, model}
    # alone describes a join that knows both dimensions.
    complete = has_hw and has_model
    if complete:
        tags = [t for t in tags if t not in ("hw", "model")]
    elif "hw" in tags:
        # names the hardware dim it lacks; the model dim is also unestablished
        tags = ["model", "hw"] + [t for t in tags if t not in ("model", "hw")]
    elif not has_model:
        tags.append("model")
    # canonical order: model, hw, then the rest alphabetically
    head = [t for t in ("model", "hw") if t in tags]
    tail = sorted(t for t in tags if t not in head)
    return head + tail


def canonicalize(
    raw: Mapping[str, Any],
    *,
    source_key: Optional[str] = None,
    today: Optional[str] = None,
    assign_id: bool = True,
    run_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Turn a raw scraper emit into a stored-row shaped dict.

    * normalises strings, slugs, evidence, missing
    * derives `id` when absent (CONTRACT §2)
    * defaults optional fields (never invents required ones)
    * records corrections in `row["missing_fixed"]` when enumerate_missing()
      had to upgrade the scraper's missing list

    Raises RowError for hard structural problems (not a mapping, unknown
    fields) so a typo'd field is visible instead of silently dropped.
    """
    if not isinstance(raw, Mapping):
        raise RowError([f"row is not an object: {type(raw).__name__}"])

    src = dict(raw)
    for alias, target in _ALIASES.items():
        if alias in src and target not in src:
            src[target] = src.pop(alias)

    unknown = sorted(k for k in src if k not in _KNOWN_FIELDS)
    if unknown:
        raise RowError([f"unknown field(s): {', '.join(unknown)}"])

    fixed: List[str] = []
    row: Dict[str, Any] = {}

    # --- identity / enums -------------------------------------------------
    status = _clean_str(src.get("status"))
    row["status"] = status.lower() if status else status
    kind = _clean_str(src.get("source_kind"))
    row["source_kind"] = kind.lower() if kind else kind
    row["provisional"] = _as_bool(src.get("provisional"), False)

    # --- hardware ---------------------------------------------------------
    vendor = _clean_str(src.get("hw_vendor"))
    row["hw_vendor"] = slugify_vendor(vendor) if vendor and vendor == vendor.lower() else vendor
    arch = _clean_str(src.get("hw_arch"))
    row["hw_arch"] = slugify_arch(arch) if arch and arch == arch.lower() else arch
    row["hw_name"] = _clean_str(src.get("hw_name"))
    extra = src.get("hw_extra")
    row["hw_extra"] = dict(extra) if isinstance(extra, Mapping) else {}

    # --- model ------------------------------------------------------------
    family = _clean_str(src.get("model_family"))
    row["model_family"] = slugify_model(family) if family and family == family.lower() else family
    row["model_rev"] = _clean_str(src.get("model_rev"))
    row["quant"] = _clean_str(src.get("quant"))

    # --- runtime ----------------------------------------------------------
    runtime = _clean_str(src.get("runtime"))
    row["runtime"] = slugify_runtime(runtime) if runtime and runtime == runtime.lower() else runtime
    rev = _clean_str(src.get("runtime_rev"))
    row["runtime_rev"] = rev

    # --- pointer / prose --------------------------------------------------
    pointer = _clean_str(src.get("pointer"))
    if pointer and not re.match(r"^https?://", pointer, re.I):
        fixed.append(f"pointer not http(s), dropped: {pointer[:80]!r}")
        pointer = None
    row["pointer"] = pointer
    row["notes"] = _clean_str(src.get("notes"))
    meas = src.get("measurement")
    row["measurement"] = dict(meas) if isinstance(meas, Mapping) else None

    # --- dates / provenance ----------------------------------------------
    as_of = src.get("as_of")
    if as_of is None:
        fixed.append(f"as_of defaulted to {today or globals()['today']()}")
        as_of = today or globals()["today"]()
    row["as_of"] = as_of if isinstance(as_of, str) else str(as_of)

    reported_by = _clean_str(src.get("reported_by"))
    if reported_by is None:
        if source_key:
            reported_by = f"scraper:{source_key}"
            fixed.append(f"reported_by defaulted to {reported_by!r} from source key")
        elif row["source_kind"] in SOURCE_KINDS:
            reported_by = f"{row['source_kind']}:unattributed"
            fixed.append(f"reported_by defaulted to {reported_by!r}")
    row["reported_by"] = reported_by

    # first_seen/updated are pipeline-owned (CONTRACT §1: scrapers must not set
    # them).  Stamp them with the run date here so a canonicalised row already
    # satisfies §1; the normalizer recomputes first_seen across the merge.
    stamp = run_date if (isinstance(run_date, str) and parse_date(run_date)) else None
    for f in ("first_seen", "updated"):
        v = src.get(f)
        row[f] = v if isinstance(v, str) and parse_date(v) else stamp

    # --- pointer_alive: set by the link-checker, true at creation --------
    row["pointer_alive"] = _as_bool(src.get("pointer_alive"), True)

    # --- votes ------------------------------------------------------------
    try:
        votes = int(src.get("want_votes") or 0)
    except (TypeError, ValueError):
        votes = 0
    row["want_votes"] = max(0, votes)
    wf = src.get("want_first")
    row["want_first"] = wf if isinstance(wf, str) and parse_date(wf) else None
    row["want_requesters"] = _clean_list(src.get("want_requesters"))[:10]

    # --- evidence ---------------------------------------------------------
    row["evidence"] = _norm_evidence(src.get("evidence"))

    # --- missing / created_by --------------------------------------------
    original_missing = src.get("missing")
    new_missing = enumerate_missing(original_missing or [])
    # A scraper may declare that its join dimension set is complete (it states
    # both dimensions it joined and knows it has both); that makes missing==[]
    # an explicit claim rather than a forgotten one.
    markers_complete = _as_bool(src.get("markers_complete"), False)
    original_tags = _clean_list(original_missing or [])
    if markers_complete:
        # the source declares its join dimension set complete: an explicit
        # empty `missing` is then a claim, not a forgotten marker (but inv 9
        # still requires "model" on a `*` row)
        new_missing = [] if (row.get("model_family") or "*") != "*" else ["model"]
    star_model_gap = (row.get("model_family") or "").strip() == "*" and \
        "model" not in new_missing
    if star_model_gap:
        # CONTRACT §1 invariant 9: a `*` row always declares the model gap,
        # whatever its source_kind.
        new_missing = ["model"] + [t for t in new_missing if t != "model"]
    row["missing"] = new_missing
    # only a change that turns a STATED gap into nothing needs reporting (and
    # it then needs the markers_complete opt-in, or it stays an invalid row)
    if star_model_gap:
        fixed.append("missing {!r} -> {!r} (CONTRACT §1 invariant 9: '*' rows declare "
                     "the model gap)".format(original_tags, new_missing))
        row["missing_fixed"] = fixed[-1]
        reduced_to_nothing = False
    else:
        reduced_to_nothing = bool(original_tags) and not new_missing
    if reduced_to_nothing and not markers_complete:
        if row["source_kind"] == "derived":
            # a derived row may not be marker-free (inv 3): keep the marker and
            # say so -- the emit must opt in to a complete-join claim.
            fixed.append(
                "missing {!r} -> [] would leave a derived row with no marker "
                "(CONTRACT §1 inv 3). Set markers_complete:true on the emit if "
                "the join really verified every dimension".format(original_tags)
            )
            # a dimension the row DOES have is not "missing": keep only the
            # dimensions it really lacks, and a model-level gap while the row
            # still carries no model-specific information.
            dims = set(original_tags)
            kept = [t for t in original_tags if t != "model"]
            if "hw" not in original_tags:
                kept.append("model")
            if not kept:
                kept = ["hw"]
            if row.get("model_family") == "*":
                # inv 9: a `*` row always declares the model gap -- which is
                # exactly the gap it has when it is not model-specific.
                kept = ["model"]
            row["missing"] = kept
            row["missing_fixed"] = fixed[-1]
        else:
            fixed.append("missing {!r} -> [] (row states every dimension)".format(original_tags))
            row["missing_fixed"] = fixed[-1]
    elif new_missing != original_tags:
        fixed.append(
            "missing upgraded {!r} -> {!r} (see CONTRACT §1 invariants 2/3)."
            .format(_clean_list(original_missing or []), new_missing)
        )
        row["missing_fixed"] = fixed[-1]
    else:
        row["missing_fixed"] = None

    # Defect C guard: a scraped row whose only evidence kind is upstream-doc
    # and whose source is a backend doc must not have missing: [] together with
    # a specific (non-*) model_family unless an evidence quote actually names
    # the model.
    if (
        row.get("source_kind") == "scraped"
        and (row.get("model_family") or "*") != "*"
        and row["missing"] == []
        and "backends" in (src.get("reported_by") or "")
    ):
        ev_kinds = {e.get("kind") for e in row["evidence"]}
        if ev_kinds == {"upstream-doc"}:
            fam_lower = row["model_family"].lower()
            if not any(fam_lower in (e.get("quote") or "").lower() for e in row["evidence"]):
                row["missing"] = ["model"]
                row["source_kind"] = "derived"
                row["missing_fixed"] = (
                    "missing [] -> ['model'] (scraped backend-doc row has no "
                    "evidence quote naming model_family; downgraded to derived)"
                )

    created = _clean_str(src.get("created_by"))
    if created:
        created = created.lower()
    elif row["source_kind"] in ("derived",):
        created = "derived"
    elif row["source_kind"] in ("scraped",):
        created = "scraper"
    elif row["source_kind"] in ("hand", "author-claim"):
        created = "hand"
    row["created_by"] = created

    # "rejected because we found nothing" (an absence claim) as opposed to
    # "rejected because it was tested and does not work".  Only the former may
    # flip to wanted on votes.  Inferred from the rejection notes when absent.
    rnc = src.get("resolves_no_claim")
    if rnc is None:
        # A rejection that carries no pointer (nothing to test against) and
        # explains itself is a "we found no support" claim: an absence claim.
        # A rejection *with* a pointer means someone evaluated real evidence.
        rnc = (row["status"] == "rejected"
               and not row["pointer"]
               and bool(row["notes"]))
        row["resolves_no_claim"] = bool(rnc)
    else:
        row["resolves_no_claim"] = _as_bool(rnc, False)
    try:
        row["miss_reports"] = int(src.get("miss_reports") or 0)
    except (TypeError, ValueError):
        row["miss_reports"] = 0
    row["markers_complete"] = markers_complete
    row["sources"] = _clean_list(src.get("sources"))
    vocab = src.get("vocabulary")
    row["vocabulary"] = vocab if isinstance(vocab, list) else []

    # --- id ---------------------------------------------------------------
    given_id = _clean_str(src.get("id"))
    if given_id:
        row["id"] = given_id
    elif assign_id:
        try:
            row["id"] = derive_id(row["hw_vendor"], row["hw_arch"],
                                  row["model_family"], row["runtime"])
        except IdError:
            row["id"] = None
    else:
        row["id"] = None

    if fixed:
        row["_fixed"] = fixed
    return row


# ---------------------------------------------------------------------------
# Validation (CONTRACT §1 invariants)
# ---------------------------------------------------------------------------

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate(
    row: Mapping[str, Any],
    *,
    taxonomy: Optional[Mapping[str, Any]] = None,
    today: Optional[str] = None,
) -> List[str]:
    """Return a list of human-readable violations ([] == valid).

    Enforces CONTRACT §1: required fields, types, enums and invariants 1-8.
    """
    errs: List[str] = []
    if not isinstance(row, Mapping):
        return [f"row is not an object: {type(row).__name__}"]

    tday = today or globals()["today"]()

    def req(name: str) -> Any:
        if name not in row or row[name] is None:
            errs.append(f"missing required field: {name}")
            return None
        return row[name]

    # -- required scalars -------------------------------------------------
    row_id = req("id")
    status = req("status")
    source_kind = req("source_kind")
    hw_vendor = req("hw_vendor")
    hw_arch = req("hw_arch")
    model_family = req("model_family")
    runtime = req("runtime")
    as_of = req("as_of")
    reported_by = req("reported_by")
    req("first_seen")
    req("updated")
    req("want_votes")
    req("want_requesters")
    # `evidence` is optional (CONTRACT §1) and validated only when present
    req("pointer_alive")

    # -- enums ------------------------------------------------------------
    if status is not None and status not in STATUSES:
        if status == "not-searched":
            errs.append("invariant 1: status 'not-searched' is unstored, never a row status")
        else:
            errs.append(f"status {status!r} not in {STATUSES}")
    if source_kind is not None and source_kind not in SOURCE_KINDS:
        errs.append(f"source_kind {source_kind!r} not in {SOURCE_KINDS}")

    vendors = HW_VENDORS
    if isinstance(taxonomy, Mapping) and isinstance(taxonomy.get("hw_vendors"), Mapping):
        vendors = tuple(taxonomy["hw_vendors"].keys())
    if hw_vendor is not None and hw_vendor not in vendors:
        errs.append(f"hw_vendor {hw_vendor!r} not in {vendors}")

    if hw_arch is not None and not isinstance(hw_arch, str):
        errs.append("hw_arch must be a string")
    elif isinstance(hw_arch, str) and not ID_SEGMENT_RE.match(hw_arch):
        errs.append(f"hw_arch {hw_arch!r} is not snake_case/kebab [a-z0-9_-]")

    if model_family is not None:
        if not isinstance(model_family, str) or not MODEL_FAMILY_RE.match(model_family):
            errs.append(f"model_family {model_family!r} is not snake_case (or '*')")

    if runtime is not None and not isinstance(runtime, str):
        errs.append("runtime must be a string")

    # -- types ------------------------------------------------------------
    if "pointer_alive" in row and not isinstance(row.get("pointer_alive"), bool):
        errs.append("pointer_alive must be bool")
    if "want_votes" in row and (not _is_int(row.get("want_votes")) or row["want_votes"] < 0):
        errs.append("want_votes must be an int >= 0")
    if "want_requesters" in row and not isinstance(row.get("want_requesters"), list):
        errs.append("want_requesters must be a list of strings")
    if "missing" in row and row.get("missing") is not None and not isinstance(row.get("missing"), list):
        errs.append("missing must be a list of strings")
    if "provisional" in row and not isinstance(row.get("provisional"), bool):
        errs.append("provisional must be bool")
    if "hw_extra" in row and row.get("hw_extra") is not None and not isinstance(row.get("hw_extra"), Mapping):
        errs.append("hw_extra must be an object")
    meas = row.get("measurement")
    if meas is not None and not isinstance(meas, Mapping):
        errs.append("measurement must be an object or null")
    created_by = row.get("created_by")
    if created_by is not None and created_by not in CREATED_BY:
        errs.append(f"created_by {created_by!r} not in {CREATED_BY}")

    # -- evidence (>=1, each {url,quote,kind}, kind enum) -----------------
    # CONTRACT §1: `evidence` is optional/nullable.  When row["evidence"] is
    # present it must be a well-formed list; when the key is absent entirely it
    # is a row that records a claim without a pasted quote (e.g. a vote-only row).
    evidence = row.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, list) or len(evidence) == 0:
            errs.append("evidence must be a list with >= 1 entry when present")
        else:
            for i, ev in enumerate(evidence):
                if not isinstance(ev, Mapping):
                    errs.append(f"evidence[{i}] is not an object")
                    continue
                url = ev.get("url")
                # http(s) for real sources; the scheme "solve.run://" is the
                # pipeline's internal reference for vote/miss derived evidence.
                if not isinstance(url, str) or not re.match(r"^(https?|solve\.run)://", url):
                    errs.append(f"evidence[{i}].url missing or not http(s)")
                if not isinstance(ev.get("quote"), str) or not ev.get("quote", "").strip():
                    errs.append(f"evidence[{i}].quote missing or empty")
                if ev.get("kind") not in EVIDENCE_KINDS:
                    errs.append(f"evidence[{i}].kind {ev.get('kind')!r} not in {EVIDENCE_KINDS}")

    # -- dates ------------------------------------------------------------
    if as_of is not None:
        if not isinstance(as_of, str) or not DATE_RE.match(as_of):
            errs.append(f"as_of {as_of!r} does not match YYYY-MM-DD")
        elif parse_date(as_of) is None:
            errs.append(f"as_of {as_of!r} is not a real calendar date")
        elif as_of > tday:
            errs.append(f"as_of {as_of!r} is in the future (today {tday})")
    for f in ("first_seen", "updated"):
        v = row.get(f)
        if v is not None and (not isinstance(v, str) or parse_date(v) is None):
            errs.append(f"{f} {v!r} does not match YYYY-MM-DD")
    wf = row.get("want_first")
    if wf is not None and (not isinstance(wf, str) or parse_date(wf) is None):
        errs.append(f"want_first {wf!r} does not match YYYY-MM-DD")

    # -- invariant 1: status/pointer --------------------------------------
    pointer = row.get("pointer")
    notes = row.get("notes")
    missing = row.get("missing") or []
    want_votes = row.get("want_votes")
    want_first = row.get("want_first")

    if status == "solved" and not pointer:
        errs.append("invariant 1: status 'solved' requires a non-null pointer")

    # -- invariant 2 (amended): scraped rows are complete claims ----------
    # "Complete" means: no gap markers, OR exactly ["model"] on a "*" row --
    # a `*` row names the dimension it omits, which is what makes it honest.
    if source_kind == "scraped":
        if not pointer:
            errs.append("invariant 2: source_kind 'scraped' requires a non-null pointer")
        complete = (len(missing) == 0
                    or (list(missing) == ["model"] and model_family == "*"))
        if not complete:
            errs.append(f"invariant 2: source_kind 'scraped' is incomplete: expected "
                        f"missing == [] or missing == ['model'] with model_family '*', "
                        f"got missing={list(missing)!r}, model_family={model_family!r}")

    # -- invariant 3: derived rows state what they lack -------------------
    # (an explicit `markers_complete: true` join has verified every dimension,
    #  so it has nothing to state -- only that declaration may be empty)
    # (a `*` row can never be marker-free: invariant 9 guarantees its "model")
    if source_kind == "derived" and len(missing) < 1 and not row.get("markers_complete") \
            and model_family != "*":
        errs.append("invariant 3: source_kind 'derived' requires missing to be non-empty")

    # -- invariant 4: wanted rows are voted ------------------------------
    if status == "wanted":
        if not (_is_int(want_votes) and want_votes >= 1):
            errs.append("invariant 4: status 'wanted' requires want_votes >= 1")
        if not want_first:
            errs.append("invariant 4: status 'wanted' requires a non-null want_first")

    # -- invariant 5: rejected rows explain themselves -------------------
    if status == "rejected" and not notes:
        errs.append("invariant 5: status 'rejected' requires notes explaining why")

    # -- invariant 6: runtime_rev is never a floating ref -----------------
    rev = row.get("runtime_rev")
    if rev == "":
        errs.append("invariant 6: runtime_rev is empty (must be null or a pinned ref)")
    elif isinstance(rev, str) and rev.lower() in BANNED_RUNTIME_REVS:
        errs.append(f"invariant 6: runtime_rev {rev!r} is a floating ref (latest/master/main/HEAD/empty)")

    # -- invariant 9: a "*" row always declares the model gap --------------
    if model_family == "*" and "model" not in (missing or []):
        errs.append("invariant 9: model_family '*' requires 'model' in missing")

    # -- invariant 8: id derivation --------------------------------------
    # CONTRACT, read literally and both halves honoured:
    #   §1 inv 8: id == slug(hw_vendor) + "/" + slug(hw_arch) + "/" +
    #             slug(model_family) + "/" + runtime_slug
    #   §2:       "Dots are not allowed in id segments -- `_` and `-` only."
    # For most fields the slug is the field itself.  Model families are the
    # documented exception (the contract's own example uses a dotted
    # model_family, e.g. qwen2.5), so '.' -> '_' there is §2 applied, not a
    # rewrite.  Everything else must match exactly; a dot anywhere else in an
    # id segment is reported as a §2 violation.
    if row_id is not None:
        if not isinstance(row_id, str):
            errs.append("id must be a string")
        elif all(v is not None for v in (hw_vendor, hw_arch, model_family, runtime)):
            try:
                expected = derive_id(hw_vendor, hw_arch, model_family, runtime)
            except IdError as exc:
                errs.extend(f"invariant 8: {e}" for e in exc.errors)
            else:
                if row_id != expected:
                    errs.append(f"invariant 8: id {row_id!r} != derived {expected!r}")
        segs = row_id.split("/")
        fields = (hw_vendor, hw_arch, model_family, runtime)
        for i, seg in enumerate(segs):
            if "." not in seg or i >= len(fields) or fields[i] is None:
                continue
            f = fields[i]
            if i == 2:
                ok = seg == model_id_segment(f)
            else:
                ok = seg == _slugify(f)
            if not ok:
                field = ("hw_vendor", "hw_arch", "model_family", "runtime")[i]
                errs.append(f"invariant 8 (§2): id segment {seg!r} contains '.' "
                            f"(ids use '_' or '-'; {field}={f!r})")
    return errs


def validate_errors(row: Mapping[str, Any], *, taxonomy=None, today=None) -> Dict[str, List[str]]:
    """Group violations by invariant tag (e.g. 'invariant 2') for reporting."""
    grouped: Dict[str, List[str]] = {}
    for e in validate(row, taxonomy=taxonomy, today=today):
        tag = e.split(":", 1)[0] if re.match(r"^(invariant \d|missing required field|status|source_kind|hw_|model_|runtime|evidence|as_of|first_seen|updated|want_|pointer_alive|provisional|id|created_by|measurement|hw_extra)", e) else "schema"
        grouped.setdefault(tag.strip(), []).append(e)
    return grouped


def is_valid(row: Mapping[str, Any], *, taxonomy=None, today=None) -> bool:
    return not validate(row, taxonomy=taxonomy, today=today)


def base_score(row: Mapping[str, Any]) -> int:
    """Number of non-null, non-empty fields -- merge tie-break (CONTRACT §5)."""
    n = 0
    for k, v in row.items():
        if k.startswith("_") or k in ("first_seen", "updated", "sources", "vocabulary"):
            continue
        if v is None:
            continue
        if isinstance(v, (str, list, dict)) and len(v) == 0:
            continue
        n += 1
    return n


__all__ = [
    "ROWS_CONTRACT_VERSION", "STATUSES", "SOURCE_KINDS", "SOURCE_KIND_RANK",
    "CREATED_BY", "EVIDENCE_KINDS", "HW_VENDORS", "BANNED_RUNTIME_REVS",
    "RowError", "IdError", "now", "today", "parse_date",
    "derive_id", "parse_id", "slugify_vendor", "slugify_arch", "slugify_model",
    "model_id_segment", "slugify_runtime", "runtime_id_segment",
    "canonicalize", "enumerate_missing", "validate", "validate_errors",
    "is_valid", "base_score",
]
