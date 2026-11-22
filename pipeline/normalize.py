"""Normalizer: scrapers/out/*.jsonl (+ stored data/rows/*.jsonl) -> data/rows/<vendor>.jsonl

Implements CONTRACT.md §5:

  * input   scrapers/out/<source_key>.jsonl (any subset present, any order,
            dupes allowed) plus the *already stored* rows in data/rows/ so that
            nothing is ever lost downstream;
  * validate every incoming row against CONTRACT §1 (pipeline.schema.validate)
            -- rejects are reported, counted, and never silently repaired;
  * merge on `id`.  Higher source_kind rank wins the base:
            author-claim > hand > scraped > derived.  Equal rank: more
            non-null fields wins, tie -> later as_of;
  * first_seen = min across merged, updated = the pipeline's date, as_of =
            the stored row's (CONTRACT: the merge winner supplies the claim);
  * evidence = union deduped on url (cap 8);
  * pointer_alive is *not* computed here.  It is copied from the stored row
            (the link-checker owns it) and defaults to true for new rows.
            A row that vanished from scrapers/out is never deleted.

Run standalone:  python3 pipeline/normalize.py [--root DIR] [--report PATH]
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

if __package__ in (None, ""):  # allow `python3 pipeline/normalize.py`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import schema, util
else:
    from . import schema, util

EVIDENCE_CAP = 8
REQUESTERS_CAP = 10


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def source_files(p: Mapping[str, str]) -> List[str]:
    files = sorted(glob.glob(os.path.join(p["scrapers_out"], "*.jsonl")))
    # side-files the scrapers may drop in out/ are not row streams
    return [f for f in files if not os.path.basename(f).startswith(("runtime_revs", "_"))]


def load_source_rows(p: Mapping[str, str]) -> Tuple[List[Tuple[str, Any, int]], List[str]]:
    """Return ([(source_key, raw_row, lineno)], warnings)."""
    out: List[Tuple[str, Any, int]] = []
    warnings: List[str] = []
    for path in source_files(p):
        key = os.path.basename(path)[:-len(".jsonl")]
        rows = util.read_jsonl(path)
        for i, raw in enumerate(rows, 1):
            out.append((key, raw, i))
    return out, warnings


def backfill_row_votes(row: Mapping[str, Any], votes: Optional[Mapping[str, Any]],
                       misses_index: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Carry an existing row's vote-derived fields through normalization.

    Votes/misses are owned by pipeline/votes.py; they are not in scrapers/out,
    so normalisation must not reset them on an unrelated re-run.
    """
    row = dict(row)
    if isinstance(votes, Mapping):
        entry = votes.get(row.get("id"))
        if isinstance(entry, Mapping):
            try:
                count = int(entry.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            if count > 0:
                row["want_votes"] = max(int(row.get("want_votes") or 0), count)
                first = entry.get("first")
                if isinstance(first, str) and schema.parse_date(first):
                    if not row.get("want_first") or first < row["want_first"]:
                        row["want_first"] = first
                reqs = [str(r) for r in (entry.get("requesters") or [])]
                merged = list(dict.fromkeys(list(row.get("want_requesters") or []) + reqs))
                row["want_requesters"] = merged[:REQUESTERS_CAP]
    return row


# ---------------------------------------------------------------------------
# Merge (CONTRACT §5)
# ---------------------------------------------------------------------------

def _metric(row: Mapping[str, Any]) -> int:
    return schema.base_score(row)


_EVIDENCE_KIND_RANK = {
    "upstream-doc": 3,
    "package-table": 3,
    "release": 3,
    "model-repo": 2,
    "issue": 1,
    "community": 0,
}


def _evidence_rank(row: Mapping[str, Any]) -> int:
    return max(
        (_EVIDENCE_KIND_RANK.get(ev.get("kind"), -1)
         for ev in (row.get("evidence") or []) if isinstance(ev, Mapping)),
        default=-1,
    )


def merge_sort_key(row: Mapping[str, Any]) -> Tuple[int, int, int, str, str]:
    """Sort candidates so candidates[0] is the merge base.

    Higher is better: source rank, evidence authority, filled fields, as_of
    (ISO dates sort lexicographically), then reported_by for byte-deterministic ties.
    """
    rank = schema.SOURCE_KIND_RANK.get(row.get("source_kind"), -1)
    return (rank, _evidence_rank(row), _metric(row), (row.get("as_of") or "")[:10], str(row.get("reported_by") or ""))


def merge_evidence(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        for ev in row.get("evidence") or []:
            url = ev.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({"url": url, "quote": ev.get("quote"), "kind": ev.get("kind")})
            if len(out) >= EVIDENCE_CAP:
                return out
    return out


def _merge_field(base: Mapping[str, Any], donors: Iterable[Mapping[str, Any]], field: str) -> Any:
    """base wins if it has a value; otherwise the highest-ranked donor."""
    val = base.get(field)
    if val not in (None, "", [], {}):
        return val
    for d in donors:
        v = d.get(field)
        if v not in (None, "", [], {}):
            return v
    return val


def merge_group(rows: List[Mapping[str, Any]], *, run_date: str) -> Dict[str, Any]:
    """Merge all candidates sharing one id into a single stored row."""
    if not rows:
        raise ValueError("merge_group needs at least one row")
    ordered = sorted(rows, key=merge_sort_key, reverse=True)
    base = dict(ordered[0])
    donors = ordered[1:]
    merged = dict(base)

    for field in ("hw_name", "hw_extra", "model_rev", "quant", "runtime_rev",
                  "pointer", "notes", "measurement", "provisional"):
        if field == "provisional":
            merged[field] = bool(base.get(field)) or any(bool(d.get(field)) for d in donors)
            continue
        merged[field] = _merge_field(base, donors, field)

    # sources: every scraper that touched this id, for provenance traceability.
    srcs: List[str] = []
    for r in ordered:
        for s in (r.get("sources") or []):
            if s not in srcs:
                srcs.append(s)
        rb = r.get("reported_by")
        if rb and rb not in srcs:
            srcs.append(rb)
    merged["sources"] = srcs

    # vocabulary: honour the explicit-scope rule instead of unioning.
    # CONTRACT §5 "Model-specific beats `*`": if a dot-free id collision puts a
    # `*` row and a model-specific row under one id, the model-specific family
    # wins.  This is deliberate: downgrading a complete claim to "applies to all
    # models" would make it invalid under §1 invariant 2.
    base_vocab = base.get("vocabulary") or []
    has_model_scope = any("model" in (r.get("vocabulary") or []) for r in ordered)
    # Collision detection that does not depend on scrapers emitting a
    # `vocabulary` field: two non-`*` families, or a `*` next to another
    # family, for the same id.
    families = {r.get("model_family") for r in ordered if r.get("model_family")}
    model_family_rows = [r for r in ordered if r.get("model_family") not in (None, "*")]
    star_family = "*" in families
    if base.get("model_family") == "*" and model_family_rows:
        best = sorted(model_family_rows, key=merge_sort_key, reverse=True)[0]
        merged["model_family"] = best.get("model_family")
        merged["model_rev"] = best.get("model_rev") or merged.get("model_rev")
        merged["quant"] = best.get("quant") or merged.get("quant")
        if has_model_scope:
            merged["vocabulary"] = [v for v in base_vocab if v != "model"] + ["model"]
        rest = [m for r in ordered for m in (r.get("missing") or []) if m != "model"]
        merged["missing"] = list(dict.fromkeys(rest))
        if not merged["missing"]:
            # No marker left, but the base was derived/scraped and a derived row
            # must state what it lacks: the join picked up a model but is still
            # a synthesis, so it records the hardware dimension it did not verify.
            merged["missing"] = ["hw"]
        merged["missing_fixed"] = ("model-specific row won the merge for {!r} "
                                   "(CONTRACT §5); missing recomputed".format(merged["id"]))
    elif base.get("model_family") == "*" and star_family and (
            "model" not in (merged.get("missing") or [])):
        merged["missing"] = ["model"] + [m for m in (merged.get("missing") or []) if m != "model"]

    # first_seen = min across merged; updated = pipeline clock (today)
    dates = [r.get("first_seen") for r in ordered if schema.parse_date(r.get("first_seen"))]
    entries = [r.get("as_of") for r in ordered if schema.parse_date(r.get("as_of"))]
    merged["first_seen"] = min(dates) if dates else (min(entries) if entries else run_date)
    merged["updated"] = run_date
    # as_of = the merge winner's claim date.  A stored row is a *donor* here, so
    # if it wins the base its (possibly human-edited) date is preserved.
    merged["as_of"] = base.get("as_of") or (max(entries) if entries else run_date)

    # pointer_alive: the link-checker owns it.  The stored row *is* its verdict
    # (CONTRACT §5: upstream disappearance is its job), so it overrides the
    # scraper's creation-time default.  New rows start alive (CONTRACT §1).
    stored = next((r for r in rows if r.get("first_seen") and r.get("updated")
                   and r.get("_stored")), None)
    merged["pointer_alive"] = bool(base.get("pointer_alive", True))
    if stored is not None and merged.get("pointer"):
        merged["pointer_alive"] = bool(stored.get("pointer_alive", True))
    if merged.get("pointer_alive") is False and not merged.get("pointer"):
        merged["pointer_alive"] = True

    # evidence union
    merged["evidence"] = merge_evidence([base] + [d for d in donors if d.get("evidence")])

    # A `scraped` row is a complete claim (inv 2): it may not inherit a `*`
    # model_family or a non-empty `missing` from a lower-ranked donor.  Keep the
    # §5 rank for every other field, but let the model dimension and the gap
    # markers follow the highest-ranked row that actually has them.
    if merged.get("model_family") == "*":
        claimed = [r for r in ordered if r.get("model_family") not in (None, "*")
                   and r.get("source_kind") == merged.get("source_kind")]
        if claimed:
            best = claimed[0]
            merged["model_family"] = best.get("model_family")
            merged["model_rev"] = best.get("model_rev")
            merged["quant"] = merged.get("quant") or best.get("quant")
    if merged.get("source_kind") == "scraped" and merged.get("missing"):
        complete = [r for r in ordered
                    if r.get("source_kind") == "scraped" and not (r.get("missing") or [])]
        if complete:
            merged["missing"] = []
            if merged.get("model_family") == "*":
                merged["model_family"] = complete[0].get("model_family")

    # created_by: the base kind's natural creator unless the base says otherwise
    merged["created_by"] = base.get("created_by")
    merged["missing_fixed"] = base.get("missing_fixed")
    if base.get("pointer_alive") is False and merged.get("pointer") is None:
        merged["pointer_alive"] = True
    return merged


def _stored_only_rows(stored: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return stored


def _wire_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Remove pipeline-internal helper keys before writing to disk."""
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in ("missing_fixed",)}


# ---------------------------------------------------------------------------
# Normalisation pass
# ---------------------------------------------------------------------------

class Rejects:
    """Collects validator rejections with provenance for the build report."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def add(self, source: str, lineno: int, raw: Any, errors: List[str]) -> None:
        self.items.append({
            "source": source, "line": lineno,
            "id": (raw.get("id") if isinstance(raw, Mapping) else None),
            "runtime": (raw.get("runtime") if isinstance(raw, Mapping) else None),
            "status": (raw.get("status") if isinstance(raw, Mapping) else None),
            "source_kind": (raw.get("source_kind") if isinstance(raw, Mapping) else None),
            "errors": sorted(set(errors)),
        })

    def counts(self) -> Dict[str, int]:
        c: Dict[str, int] = {}
        for it in self.items:
            tag = it["errors"][0].split(":", 1)[0]
            c[tag] = c.get(tag, 0) + 1
        return dict(sorted(c.items()))

    def fingerprints(self) -> List[Dict[str, Any]]:
        """Collapse identical error signatures so the report stays readable."""
        seen: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for it in self.items:
            sig = (tuple(it["errors"]), it["source"])
            ent = seen.setdefault(sig, {"errors": it["errors"], "source": it["source"],
                                        "count": 0, "example": it})
            ent["count"] += 1
        return sorted(seen.values(), key=lambda e: (-e["count"], e["errors"][0]))

    def __len__(self) -> int:
        return len(self.items)


def normalize(
    p: Mapping[str, str],
    *,
    run_date: Optional[str] = None,
    taxonomy: Optional[Mapping[str, Any]] = None,
    write: bool = True,
    noisy: bool = True,
) -> Dict[str, Any]:
    """Run the normalisation pass.  Returns a report dict.

    Reads  scrapers/out/*.jsonl + data/rows/*.jsonl
    Writes data/rows/<hw_vendor>.jsonl (sorted by id)
    """
    tday = run_date or schema.today()
    if taxonomy is None:
        taxonomy = util.load_taxonomy(p)
    votes = util.read_json(p["votes"], default={}) or {}

    rejects = Rejects()
    warnings: List[str] = []
    stored_repaired: List[str] = []

    # 1. stored rows (they are donors, never candidates for deletion)
    stored: Dict[str, Dict[str, Any]] = {}
    for path in sorted(glob.glob(os.path.join(p["rows_dir"], "*.jsonl"))):
        for raw in util.read_jsonl(path):
            if not isinstance(raw, Mapping):
                warnings.append(f"{util.rel(path, p['root'])}: non-object line skipped")
                continue
            rid = raw.get("id")
            if not rid:
                warnings.append(f"{util.rel(path, p['root'])}: stored row without id skipped")
                continue
            row = dict(raw)
            # Stored rows are brought up to the current invariants in place:
            # inv 9 (a `*` row declares the model gap) and inv 2 (a scraped row
            # is complete -- no markers other than the declared `*` gap).
            if row.get("model_family") == "*" and "model" not in (row.get("missing") or []):
                row["missing"] = ["model"] + [m for m in (row.get("missing") or []) if m != "model"]
                stored_repaired.append(f"{rid}: inv 9 marker added")
            if row.get("source_kind") == "scraped":
                m = row.get("missing") or []
                if m and not (m == ["model"] and row.get("model_family") == "*"):
                    row["missing"] = []
                    stored_repaired.append(f"{rid}: inv 2 markers dropped")
            stored[str(rid)] = row

    # 2. incoming rows
    incoming, load_warnings = load_source_rows(p)
    warnings.extend(load_warnings)
    candidates: Dict[str, List[Dict[str, Any]]] = {}
    per_source: Dict[str, Dict[str, int]] = {}
    per_source_notes: Dict[str, set] = {}
    seen_notes: Dict[Tuple[str, str], int] = {}
    rejected = 0
    for source, raw, lineno in incoming:
        stats = per_source.setdefault(source, {"rows_in": 0, "accepted": 0, "rejected": 0})
        stats["rows_in"] += 1
        try:
            row = schema.canonicalize(raw, source_key=source, today=tday, run_date=tday)
        except schema.RowError as exc:
            rejects.add(source, lineno, raw, exc.errors)
            stats["rejected"] += 1
            continue
        if "_fixed" in row:
            for note in row.pop("_fixed"):
                key = (source, note)
                seen_notes[key] = seen_notes.get(key, 0) + 1
        if row.get("missing_fixed"):
            # grouped per source below ("corrected xN ..."), not a raw warning
            key = (source, row["missing_fixed"])
            seen_notes[key] = seen_notes.get(key, 0) + 1
        errs = schema.validate(row, taxonomy=taxonomy, today=tday)
        if errs and row.get("missing_fixed"):
            # The correction already logged above makes the row valid; validate
            # the corrected form (a fix is reported, not silently applied).
            fixed = dict(row)
            fixed.pop("missing_fixed", None)
            errs = schema.validate(fixed, taxonomy=taxonomy, today=tday)
        if errs:
            rejects.add(source, lineno, row, errs)
            stats["rejected"] += 1
            del row["missing_fixed"]
            continue
        del row["missing_fixed"]
        row = backfill_row_votes(row, votes)
        candidates.setdefault(row["id"], []).append(row)
        stats["accepted"] += 1

    # 3. merge: for every id, donors = incoming candidates + stored row
    all_ids = set(candidates) | set(stored)
    merged_rows: List[Dict[str, Any]] = []
    summary = {"ids": len(all_ids), "from_scrapers": len(candidates),
               "stored_only": 0, "impossible": 0, "impossible_ids": []}
    for rid in sorted(all_ids):
        group: List[Dict[str, Any]] = list(candidates.get(rid, []))
        if rid in stored:
            donor = dict(stored[rid])
            donor["_stored"] = True          # marks the link-checker's verdict
            group.append(donor)
        else:
            summary["stored_only"] += 1
        if not candidates.get(rid) and rid in stored:
            # vanished upstream: keep exactly as stored except first_seen/updated
            row = dict(stored[rid])
            row["first_seen"] = schema.parse_date(row.get("first_seen")) or row.get("as_of") or tday
            row["updated"] = tday
            merged_rows.append(row)
            continue
        merged = merge_group(group, run_date=tday)
        errs = schema.validate(merged, taxonomy=taxonomy, today=tday)
        if errs:
            # A merge that produces an invalid row must not be written: an
            # impossible row contradicted the contract.  Keep the previous
            # stored row if there was one, else report and drop the claim.
            summary["impossible"] += 1
            summary["impossible_ids"].append({"id": rid, "errors": errs})
            if rid in stored:
                row = dict(stored[rid])
                row["updated"] = tday
                merged_rows.append(row)
            continue
        merged_rows.append(_wire_row(merged))

    # 4. sort deterministically + write per-vendor files
    merged_rows.sort(key=lambda r: r["id"])
    by_vendor: Dict[str, List[Dict[str, Any]]] = {}
    for row in merged_rows:
        by_vendor.setdefault(row["hw_vendor"], []).append(row)

    written: Dict[str, int] = {}
    changed = 0
    if write:
        os.makedirs(p["rows_dir"], exist_ok=True)
        for vendor, rows in sorted(by_vendor.items()):
            path = os.path.join(p["rows_dir"], f"{vendor}.jsonl")
            if util.write_jsonl(path, rows):
                changed += 1
            written[vendor] = len(rows)
        # Remove vendor files that no longer have any rows (only when empty).
        keep = {f"{v}.jsonl" for v in by_vendor}
        for path in glob.glob(os.path.join(p["rows_dir"], "*.jsonl")):
            if os.path.basename(path) not in keep:
                if not util.read_jsonl(path):
                    os.unlink(path)
                    warnings.append(f"removed empty row file {util.rel(path, p['root'])}")
                else:
                    warnings.append(f"row file {util.rel(path, p['root'])} has rows but no vendor?")

    corrections: Dict[str, int] = {}
    for (src, msg), n in seen_notes.items():
        corrections[f"{src}: {msg}"] = n
    report = {
        "run_date": tday,
        "corrections": dict(sorted(corrections.items(), key=lambda kv: (-kv[1], kv[0]))),
        "rows_total": len(merged_rows),
        "rows_written": sum(written.values()),
        "files_written": len(written),
        "files_changed": changed,
        "sources": dict(sorted(per_source.items())),
        "sources_present": len(per_source),
        "rejects": {"count": len(rejects), "by_error": rejects.counts(),
                    "fingerprints": rejects.fingerprints(), "items": rejects.items},
        "summary": summary,
        "warnings": warnings,
        "stored_repaired": stored_repaired,
        "rows": merged_rows,   # always returned: build.py folds votes on these
    }
    if noisy:
        log_normalize(report)
    return report


def log_normalize(report: Mapping[str, Any]) -> None:
    print(f"[normalize] date {report['run_date']}  sources {report['sources_present']}  "
          f"ids {report['summary']['ids']}  rows {report['rows_total']}  "
          f"rejects {report['rejects']['count']}")
    for src, st in report["sources"].items():
        if st["rejected"]:
            print(f"  {src:<22} in {st['rows_in']:>4}  ok {st['accepted']:>4}  "
                  f"REJECTED {st['rejected']:>4}")
    for fp in report["rejects"]["fingerprints"][:12]:
        print(f"  reject x{fp['count']:<3} [{fp['source']}] {fp['errors'][0]}")
    for msg, n in report.get("corrections", {}).items():
        print(f"  corrected x{n:<3} {msg}")
    for item in report["summary"].get("impossible_ids", [])[:8]:
        print(f"  IMPOSSIBLE MERGE {item['id']}: {item['errors'][0]}")


def load_rows(p: Mapping[str, str]) -> List[Dict[str, Any]]:
    """Load all stored rows, sorted by id (the single source of truth for export)."""
    rows: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(p["rows_dir"], "*.jsonl"))):
        for row in util.read_jsonl(path):
            if isinstance(row, dict) and row.get("id"):
                rows.append(row)
    rows.sort(key=lambda r: r["id"])
    return rows


def write_rows(p: Mapping[str, str], rows: Iterable[Mapping[str, Any]]) -> int:
    """Rewrite data/rows/*.jsonl from a full row list.  Returns files changed."""
    rows = sorted(rows, key=lambda r: r["id"])
    by_vendor: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        by_vendor.setdefault(row["hw_vendor"], []).append(row)
    changed = 0
    for vendor, vrows in by_vendor.items():
        path = os.path.join(p["rows_dir"], f"{vendor}.jsonl")
        if util.write_jsonl(path, vrows):
            changed += 1
    return changed


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="normalize scrapers/out -> data/rows")
    ap.add_argument("--root", default=None, help="project root (default: repo root)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    p = util.paths(args.root)
    report = normalize(p, write=not args.dry_run)
    return 0 if report["rows_total"] or not report["sources_present"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
