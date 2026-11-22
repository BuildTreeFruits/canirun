"""Votes + misses -> wanted rows.

Two inputs, both owned by the pipeline (CONTRACT §7):

  data/votes.json    {"<row_id>": {"count": n, "requesters": ["<stable key>", ...],
                                    "first": "YYYY-MM-DD"}}
                     written by the vote service (api/server.py) and, for demo
                     purposes only, by pipeline/seed_votes.py -> data/demo.votes.json
  data/misses.jsonl  one JSON object per line:
                     {"ts", "query": {"hw","model","runtime",...}, "query_id",
                      "searcher_key", "user_agent"}

Rules
-----
* want_votes / want_first / want_requesters (cap 10) are copied onto the row.
* A row with derived/scraped provenance is promoted to status "wanted" when it
  crosses VOTE_THRESHOLD and has **no solved pointer** (pointer is null).
  A promoted scraper row loses its pointer claim under the vote rule ("only if
  it has no solved pointer"), so the pointer moves into `evidence` and the row
  becomes an honest `hand` row created by a vote: derived/scraped rows must
  keep at least one missing marker (invariants 2/3), which an unpointed
  'wanted' claim cannot do without lying.
* A row that is already "solved" is **never downgraded**.
* A miss on (hw, model, runtime) reported by >= MISS_THRESHOLD distinct
  searcher keys auto-creates a provisional wanted row (source_kind "hand",
  created_by "miss", provisional true, notes "auto-created from N miss reports").
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import schema, util
else:
    from . import schema, util

VOTE_THRESHOLD = 1          # 1 vote is enough to record a want (blueprint: "one click")
MISS_THRESHOLD = 3          # distinct searchers before a miss creates a row
REQUESTERS_CAP = 10
EVIDENCE_CAP = 8


# ---------------------------------------------------------------------------
# votes.json
# ---------------------------------------------------------------------------

def load_votes(path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    data = util.read_json(path, default={}) if path else {}
    if not isinstance(data, Mapping):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for rid, entry in data.items():
        if isinstance(entry, int) and not isinstance(entry, bool):
            entry = {"count": entry}
        if not isinstance(entry, Mapping):
            continue
        requesters = [str(r) for r in (entry.get("requesters") or []) if str(r).strip()]
        try:
            count = int(entry.get("count") or len(requesters) or 0)
        except (TypeError, ValueError):
            count = len(requesters)
        # the requester list is authoritative for identity; count can be higher
        # (aggregated historic votes), never lower than distinct requesters.
        count = max(count, len(set(requesters)), 0)
        first = entry.get("first")
        if not (isinstance(first, str) and schema.parse_date(first)):
            first = entry.get("first_at")
        if not (isinstance(first, str) and schema.parse_date(first)):
            first = None
        if count <= 0:
            continue
        out[str(rid)] = {"count": count, "requesters": requesters[:REQUESTERS_CAP], "first": first}
    return out


def merge_vote_sources(*sources: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Union of several votes maps (real votes + demo votes); max count, earliest first."""
    out: Dict[str, Dict[str, Any]] = {}
    for src in sources:
        for rid, entry in (src or {}).items():
            cur = out.get(rid)
            if cur is None:
                out[rid] = {"count": entry["count"], "requesters": list(entry["requesters"]),
                            "first": entry.get("first")}
                continue
            reqs = list(dict.fromkeys(cur["requesters"] + list(entry["requesters"])))
            firsts = [f for f in (cur.get("first"), entry.get("first")) if f]
            out[rid] = {"count": max(cur["count"], entry["count"], len(reqs)),
                        "requesters": reqs[:REQUESTERS_CAP],
                        "first": min(firsts) if firsts else None}
    return out


# ---------------------------------------------------------------------------
# misses.jsonl
# ---------------------------------------------------------------------------

def _miss_key(rec: Mapping[str, Any]) -> Optional[Tuple[str, str, str]]:
    q = rec.get("query") if isinstance(rec.get("query"), Mapping) else rec
    if not isinstance(q, Mapping):
        return None
    hw = schema.slugify_arch(q.get("hw")) if q.get("hw") else ""
    model = schema.slugify_model(q.get("model")) if q.get("model") else ""
    runtime = schema.slugify_runtime(q.get("runtime")) if q.get("runtime") else ""
    if not (hw and model) or model == "*":
        # a miss needs a concrete card and model: "*" is never a query family
        return None
    return (hw, model, runtime or "unknown")


def _miss_searcher(rec: Mapping[str, Any]) -> str:
    for k in ("searcher_key", "voter", "session", "ip"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    ua = rec.get("user_agent")
    return f"anon:{str(ua)[:40]}" if ua else "anon:unknown"


def fold_misses(
    rows: Iterable[Mapping[str, Any]],
    misses: Iterable[Mapping[str, Any]],
    *,
    run_date: str,
    threshold: int = MISS_THRESHOLD,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fold miss reports into rows.  Returns (rows, new_rows, skipped)."""
    rows = [dict(r) for r in rows]
    existing = {r["id"]: r for r in rows}
    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    skipped: List[Dict[str, Any]] = []
    for i, rec in enumerate(misses, 1):
        if not isinstance(rec, Mapping):
            skipped.append({"line": i, "reason": "not-an-object"})
            continue
        key = _miss_key(rec)
        if key is None:
            skipped.append({"line": i, "reason": "query lacks hw/model or model is '*'",
                            "query": rec.get("query")})
            continue
        g = groups.setdefault(key, {"searchers": {}, "first": None, "last": None})
        g["searchers"].setdefault(_miss_searcher(rec), 0)
        g["searchers"][_miss_searcher(rec)] += 1
        ts = str(rec.get("ts") or "")
        day = ts[:10] if schema.parse_date(ts[:10]) else run_date
        g["first"] = day if g["first"] is None else min(g["first"], day)
        g["last"] = day if g["last"] is None else max(g["last"], day)

    new_rows: List[Dict[str, Any]] = []
    for (hw, model, runtime), g in sorted(groups.items()):
        n = len(g["searchers"])
        if n < threshold:
            continue
        # is there already a row answering hw x model x runtime (or vendor-level)?
        vid = f"{hw}/{model}/{runtime}"
        existing_row = existing.get(vid)
        if existing_row is not None:
            if existing_row.get("status") != "solved":
                existing_row["want_votes"] = max(int(existing_row.get("want_votes") or 0), n)
                if not existing_row.get("want_first") or g["first"] < existing_row["want_first"]:
                    existing_row["want_first"] = g["first"]
                existing_row.setdefault("miss_reports", n)
            continue
        vendor = _vendor_for(hw)
        rid = f"{vendor}/{hw}/{model}/{runtime}"
        if rid in existing:
            continue
        row = {
            "id": rid,
            "status": "wanted",
            "source_kind": "hand",
            "provisional": True,
            "hw_vendor": vendor,
            "hw_arch": hw,
            "hw_name": None,
            "hw_extra": {},
            "model_family": model,
            "model_rev": None,
            "quant": None,
            "runtime": runtime,
            "runtime_rev": None,
            "pointer": None,
            "notes": f"auto-created from {n} miss reports",
            "measurement": None,
            "pointer_alive": True,
            "as_of": g["last"] or run_date,
            "reported_by": "pipeline:miss-threshold",
            "first_seen": run_date,
            "updated": run_date,
            "want_votes": n,
            "want_first": g["first"] or run_date,
            "want_requesters": [],
            # A miss IS evidence (people searched and found nothing), so it is
            # recorded -- but it points at the miss log, not at an upstream doc.
            "evidence": [{
                "url": "solve.run://misses",
                "quote": f"{n} distinct searchers looked for {hw} x {model} x {runtime} "
                         f"and found nothing on record (first {g['first']}, last {g['last']}).",
                "kind": "community",
            }],
            "missing": [],
            "created_by": "miss",
            "sources": ["pipeline:miss-threshold"],
            "vocabulary": ["hw", "model", "runtime"],
            "miss_reports": n,
        }
        rows.append(row)
        new_rows.append(row)
        existing[rid] = row
    rows.sort(key=lambda r: r["id"])
    return rows, new_rows, skipped


_HW_VENDOR_HINTS = (
    ("sm_", "nvidia"), ("gfx", "amd"), ("arc-", "intel"), ("data-center-max", "intel"),
    ("flex-", "intel"), ("snapdragon", "qualcomm"), ("hexagon", "qualcomm"),
    ("m1", "apple"), ("m2", "apple"), ("m3", "apple"), ("m4", "apple"), ("m5", "apple"),
    ("aarch64", "arm-cpu"), ("arm64", "arm-cpu"), ("x86", "x86-cpu"),
)


def _vendor_for(hw_arch: str, taxonomy: Optional[Mapping[str, Any]] = None) -> str:
    """Infer hw_vendor from an arch slug using the taxonomy, then prefixes."""
    if taxonomy:
        for vendor, archs in (taxonomy.get("hw_archs") or {}).items():
            if hw_arch in (archs or []):
                return vendor
    for prefix, vendor in _HW_VENDOR_HINTS:
        if hw_arch.startswith(prefix):
            # Apple only on an exact-ish M<N> family match
            if vendor == "apple" and not (len(hw_arch) == 2 or hw_arch[2] == "-"):
                continue
            return vendor
    return "other"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def _canonical_runtime_slug(segment: str, taxonomy: Optional[Mapping[str, Any]]) -> str:
    """Map a dot-free id segment back to the taxonomy runtime slug.

    `llama_cpp` -> `llama.cpp`, `mlx-lm` -> `mlx-lm` (unchanged), `vllm` -> `vllm`.
    Exact slug match wins; otherwise compare on the flattened form so a dot in the
    slug is the only thing that can change. Unknown segments pass through verbatim.
    """
    runtimes = []
    if taxonomy:
        runtimes = taxonomy.get("runtimes") or taxonomy.get("runtime") or []
    want = str(segment or "").lower()
    for rt in runtimes:
        if isinstance(rt, Mapping):
            slug = rt.get("slug")
        else:
            slug = rt
        if not slug:
            continue
        slug = str(slug).lower()
        if slug == want:
            return slug
    for rt in runtimes:
        if isinstance(rt, Mapping):
            slug = rt.get("slug")
        else:
            slug = rt
        if not slug:
            continue
        slug = str(slug).lower()
        if slug.replace(".", "_") == want:
            return slug
    return want


def materialise_vote_row(
    row_id: str,
    entry: Mapping[str, Any],
    *,
    run_date: str,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Turn a vote on an unwritten id into a stored `wanted` row.

    The id is `vendor/arch/model/runtime` and slug-safe by construction
    (CONTRACT §2) -- except that its segments are dot-free, which is exactly
    what the row fields want for hardware.  Nothing is claimed: status wanted,
    source_kind hand, created_by vote, provisional, no pointer, and *no
    evidence* -- a vote is demand, not proof/evidence.
    """
    try:
        parts = schema.parse_id(row_id)
    except schema.IdError:
        return None
    vendor, arch, model, runtime = (parts["hw_vendor"], parts["hw_arch"],
                                    parts["model_family"], parts["runtime"])
    # The id segment is dot-free (`llama_cpp`) but the row FIELD wants the taxonomy
    # slug (`llama.cpp`). Map back through the taxonomy when we can; if the segment
    # is not a known runtime, leave it alone rather than guessing which '_' was a '.'.
    runtime = _canonical_runtime_slug(runtime, taxonomy)
    count = max(1, int(entry.get("count") or 1))
    first = entry.get("first") or run_date
    if not schema.parse_date(first):
        first = run_date
    missing = ["hw", "model"] if model == "*" else ["hw"]
    row = {
        "id": row_id,
        "status": "wanted",
        "source_kind": "hand",
        "provisional": True,
        "hw_vendor": vendor,
        "hw_arch": arch,
        "hw_name": None,
        "hw_extra": {},
        "model_family": model,
        "model_rev": None,
        "quant": None,
        "runtime": runtime,
        "runtime_rev": None,
        "pointer": None,
        "notes": "Voted for through /api/want; no claim on record yet.",
        "measurement": None,
        "pointer_alive": True,
        "as_of": first,
        "reported_by": "vote:/api/want",
        "first_seen": first,
        "updated": run_date,
        "want_votes": count,
        "want_first": first,
        "want_requesters": [str(r) for r in (entry.get("requesters") or [])][:REQUESTERS_CAP],
        # no `evidence` key at all: a vote is demand, not a quote.  (CONTRACT §1
        # treats evidence as optional; an empty list would claim "no evidence
        # found" instead of "no evidence offered".)

        "missing": missing,
        "created_by": "vote",
        "sources": ["vote:/api/want"],
        "vocabulary": ["hw", "model"],
    }
    errs = schema.validate(row, taxonomy=taxonomy, today=run_date)
    if errs:
        return None
    return row


def apply_votes(
    rows: Iterable[Mapping[str, Any]],
    votes: Mapping[str, Mapping[str, Any]],
    *,
    run_date: str,
    threshold: int = VOTE_THRESHOLD,
    taxonomy: Optional[Mapping[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply votes onto rows.  Returns (rows, events)."""
    rows = [dict(r) for r in rows]
    by_id = {r["id"]: r for r in rows}
    events: List[Dict[str, Any]] = []

    for rid in sorted(votes):
        entry = votes[rid]
        row = by_id.get(rid)
        if row is None:
            # A vote on an id with no claim is itself information: someone wants
            # this combination enough to ask for it.  Materialise a stored
            # wanted row so /api/wanted, /api/rows and combos.json agree (the
            # alternative -- a synthetic row only in the vote service -- is the
            # "two places to look" failure the project exists to prevent).
            row = materialise_vote_row(rid, entry, run_date=run_date, taxonomy=taxonomy)
            if row is None:
                events.append({"id": rid, "event": "vote-orphan", "detail":
                               "vote for an id that is not a valid row id; kept in "
                               "votes.json but not rendered"})
                continue
            rows.append(row)
            by_id[rid] = row
            events.append({"id": rid, "event": "vote-created", "votes": row["want_votes"]})
            continue
        count = int(entry.get("count") or 0)
        first = entry.get("first") or run_date
        prev_votes = int(row.get("want_votes") or 0)
        row["want_votes"] = max(prev_votes, count)
        reqs = list(dict.fromkeys(
            list(row.get("want_requesters") or []) + [str(r) for r in entry.get("requesters") or []]))
        row["want_requesters"] = reqs[:REQUESTERS_CAP]
        if row["want_votes"] > prev_votes:
            events.append({"id": rid, "event": "votes", "votes": row["want_votes"]})
        if row["status"] == "solved":
            if row.get("want_first") is None and count > 0:
                row["want_first"] = first
            continue  # NEVER downgrade a solved row
        prev_status = row["status"]
        if prev_status == "rejected" and not row.get("resolves_no_claim"):
            # a real rejection (someone tested it and it does not work) keeps
            # its status; votes are a demand signal only.  A rejection that
            # merely records "not found" is an absence claim and may flip.
            continue
        if row["want_votes"] < threshold:
            continue
        if row.get("resolves_no_claim"):
            row["as_of"] = run_date
        firsts = [x for x in (row.get("want_first"), first) if x]
        row["want_first"] = min(firsts) if firsts else run_date
        if prev_status != "wanted":
            row["status"] = "wanted"
            events.append({"id": rid, "event": "promoted", "from": prev_status,
                           "votes": row["want_votes"]})
        _make_wanted_valid(row, run_date)
    rows.sort(key=lambda r: r["id"])
    return rows, events


def strip_demo_votes(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Strip demo:* requesters and reset want_votes so non-demo builds recompute
    counts strictly from real data/votes.json and data/misses.jsonl."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        reqs = [str(req) for req in (row.get("want_requesters") or [])
                if not str(req).startswith("demo:")]
        row["want_requesters"] = reqs[:REQUESTERS_CAP]
        row["want_votes"] = 0
        out.append(row)
    return out


def _make_wanted_valid(row: Dict[str, Any], run_date: str) -> None:
    """Make a promoted row satisfy CONTRACT §1 invariants 2/3 and the 'no solved
    pointer' vote rule."""
    if row.get("source_kind") == "scraped":
        # Wanted with no solved pointer: the row may not claim completeness.
        # Move the pointer into evidence and store an honest hand/wanted row.
        ptr = row.get("pointer")
        if ptr:
            ev = row.get("evidence") or []
            if not any(e.get("url") == ptr for e in ev):
                ev.append({"url": ptr, "quote": (row.get("notes") or "pointer claimed before the vote"),
                           "kind": "community"})
            row["evidence"] = ev[:EVIDENCE_CAP]
        row["pointer"] = None
        row["source_kind"] = "hand"
        row["created_by"] = row.get("created_by") or "vote"
        if not row.get("missing"):
            row["missing"] = ["hw"]
        row["notes"] = ((row.get("notes") or "").strip()
                        + " [promoted to wanted by "
                        + str(row.get("want_votes") or 0)
                        + " vote(s); the prior pointer is kept as evidence]").strip()
    elif row.get("source_kind") == "derived":
        if not row.get("missing"):
            row["missing"] = ["hw"]
    if not row.get("want_first"):
        row["want_first"] = (row.get("want_first") or row.get("as_of") or run_date)
    if row.get("model_family") == "*" and "model" not in (row.get("missing") or []):
        row["missing"] = ["model"] + list(row.get("missing") or [])
    if int(row.get("want_votes") or 0) < 1:
        row["want_votes"] = 1


def fold_votes_file(
    p: Mapping[str, str],
    rows: Iterable[Mapping[str, Any]],
    *,
    run_date: Optional[str] = None,
    votes_files: Optional[List[str]] = None,
    misses_file: Optional[str] = None,
    taxonomy: Optional[Mapping[str, Any]] = None,
    threshold: int = VOTE_THRESHOLD,
) -> Dict[str, Any]:
    """Read votes.json (+ optional extra vote files) and misses.jsonl, fold into rows."""
    tday = run_date or schema.today()
    files = votes_files if votes_files is not None else [p["votes"]]
    loaded = [load_votes(f) for f in files if f]
    votes = merge_vote_sources(*loaded) if loaded else {}
    misses_path = misses_file if misses_file is not None else p["misses"]
    misses = util.read_jsonl(misses_path) if misses_path and os.path.exists(misses_path) else []
    rows = [dict(r) for r in rows]
    rows, events = apply_votes(rows, votes, run_date=tday, threshold=threshold, taxonomy=taxonomy)
    rows, created, skipped = fold_misses(rows, misses, run_date=tday)
    for r in created:
        events.append({"id": r["id"], "event": "miss-created", "votes": r["want_votes"]})
    # re-validate: votes must never produce an invalid row
    bad = []
    for r in rows:
        errs = schema.validate(r, taxonomy=taxonomy, today=tday)
        if errs:
            bad.append({"id": r["id"], "errors": errs})
    return {
        "run_date": tday,
        "votes_rows": len(votes),
        "misses_records": len(misses),
        "promoted": [e for e in events if e["event"] in ("promoted", "miss-created")],
        "orphan_votes": [e for e in events if e["event"] == "vote-orphan"],
        "events": events,
        "invalid_after_votes": bad,
        "created": created,
        "miss_skipped": skipped,
        "rows": rows,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="fold votes.json + misses.jsonl into data/rows")
    ap.add_argument("--root", default=None)
    ap.add_argument("--demo", action="store_true", help="also fold data/demo.votes.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    p = util.paths(args.root)
    from pipeline import normalize  # local import keeps module deps acyclic
    files = [p["votes"]]
    if args.demo:
        demo = os.path.join(p["root"], "data", "demo.votes.json")
        files.append(demo)
    rows = normalize.load_rows(p)
    rep = fold_votes_file(p, rows, votes_files=files)
    if rep["invalid_after_votes"]:
        for b in rep["invalid_after_votes"]:
            print(f"  !! vote fold produced invalid row {b['id']}: {b['errors'][0]}")
        return 2
    if not args.dry_run:
        normalize.write_rows(p, rep["rows"])
    print(f"[votes] {len(rep['rows'])} rows  votes {rep['votes_rows']}  votes-files {len(files)}  "
          f"promoted {len(rep['promoted'])}  misses {rep['misses_records']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
