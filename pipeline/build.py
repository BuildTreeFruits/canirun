"""build.py -- the one command that rebuilds the whole published dataset.

    python3 pipeline/build.py              # normalize -> votes -> misses -> export
    python3 pipeline/build.py --demo       # also fold data/demo.votes.json
    python3 pipeline/build.py --dry-run    # report only, write nothing
    python3 pipeline/build.py --check      # exit 1 if a second run would change anything

Steps
-----
1. normalize  scrapers/out/*.jsonl (+ stored rows) -> data/rows/<vendor>.jsonl   (CONTRACT §5)
2. votes      data/votes.json    -> want_votes / want_first, status promotion
3. misses     data/misses.jsonl  -> provisional wanted rows (>=3 distinct searchers)
4. export     data/rows          -> data/combos.json + data/export.jsonl         (CONTRACT §4)
5. stats      stdout report: rows by status/vendor/runtime/source_kind,
              derived rows carrying missing:["model"], dead pointers, rejects

Idempotency: a second run over unchanged inputs writes byte-identical files
(combos.json differs only in `generated_at`; its `version` does not change).
Nothing here reads the wall clock into the row data except `updated`, which
only moves when the *inputs* change -- see `--check`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import export, normalize, schema, seed_votes, util, votes as votes_mod
else:
    from . import export, normalize, schema, seed_votes, util
    from . import votes as votes_mod


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _fmt_counts(title: str, c: Mapping[str, int], *, top: Optional[int] = None) -> List[str]:
    items = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
    if top:
        shown = items[:top]
        tail = f"  (+{len(items) - top} more)" if len(items) > top else ""
    else:
        shown, tail = items, ""
    body = "  ".join(f"{k}={v}" for k, v in shown)
    total = sum(c.values())
    return [f"  {title:<14} ({total}) {body}{tail}"]


def stats(rows: List[Mapping[str, Any]], *, rejects: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    c = export.counts(rows)
    derived_missing_model = [
        r for r in rows
        if r.get("source_kind") == "derived" and "model" in (r.get("missing") or [])
    ]
    star_rows = [r for r in rows if r.get("model_family") == "*"]
    dead = [r for r in rows if r.get("pointer_alive") is False]
    provisional = [r for r in rows if r.get("provisional")]
    no_pointer = [r for r in rows if not r.get("pointer")]
    st = {
        "rows": len(rows),
        "by_status": c["by_status"],
        "by_vendor": c["by_vendor"],
        "by_runtime": c["by_runtime"],
        "by_source_kind": c["by_source_kind"],
        "derived_with_missing_model": len(derived_missing_model),
        "derived_with_missing_model_ids": [r["id"] for r in derived_missing_model][:20],
        "star_model_rows": len(star_rows),
        "pointer_alive_false": len(dead),
        "pointer_alive_false_ids": [r["id"] for r in dead][:20],
        "provisional": len(provisional),
        "rows_without_pointer": len(no_pointer),
        "solved": sum(1 for r in rows if r.get("status") == "solved"),
        "wanted": sum(1 for r in rows if r.get("status") == "wanted"),
        "rejected": sum(1 for r in rows if r.get("status") == "rejected"),
    }
    if rejects is not None:
        st["rejects"] = rejects.get("count", 0)
        st["rejects_by_error"] = rejects.get("by_error", {})
    return st


def print_stats(st: Mapping[str, Any], *, top_runtime: int = 14) -> None:
    print(f"  {'rows':<14} {st['rows']}")
    for line in _fmt_counts("by_status", st["by_status"]):
        print(line)
    for line in _fmt_counts("by_source_kind", st["by_source_kind"]):
        print(line)
    for line in _fmt_counts("by_vendor", st["by_vendor"]):
        print(line)
    for line in _fmt_counts("by_runtime", st["by_runtime"], top=top_runtime):
        print(line)
    print(f"  {'derived':<14} missing:[\"model\"] rows: {st['derived_with_missing_model']}"
          f"   '*'-model rows: {st['star_model_rows']}")
    print(f"  {'pointers':<14} pointer_alive=false: {st['pointer_alive_false']}"
          f"   no pointer: {st['rows_without_pointer']}   provisional: {st['provisional']}")
    if "rejects" in st and not st["rejects"]:
        print(f"  {'rejects':<14} 0")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _inputs_fingerprint(p: Mapping[str, str], *, demo: bool) -> Dict[str, Any]:
    """Everything whose change should move `updated` / bump the version."""
    srcs = {}
    for path in normalize.source_files(p) + sorted(
            __import__("glob").glob(os.path.join(p["rows_dir"], "*.jsonl"))):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            continue
        srcs[util.rel(path, p["root"])] = [st.st_size, int(st.st_mtime)]
    tax = {}
    for path in (p["taxonomy"], p["taxonomy_ext"]):
        try:
            st = os.stat(path)
            tax[util.rel(path, p["root"])] = [st.st_size, int(st.st_mtime)]
        except FileNotFoundError:
            continue
    votes = {}
    vote_files = [p["votes"]] + ([os.path.join(p["root"], "data", "demo.votes.json")] if demo else [])
    for path in vote_files:
        try:
            with open(path, "rb") as fh:
                votes[util.rel(path, p["root"])] = exports_hash(fh.read())
        except FileNotFoundError:
            votes[util.rel(path, p["root"])] = None
    misses = None
    try:
        with open(p["misses"], "rb") as fh:
            misses = exports_hash(fh.read())
    except FileNotFoundError:
        pass
    return {"sources": srcs, "taxonomy": tax, "votes": votes, "misses": misses,
            "demo": demo}


def exports_hash(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def _state_path(p: Mapping[str, str]) -> str:
    return os.path.join(p["root"], "pipeline", ".build-state.json")


def build(
    p: Optional[Mapping[str, str]] = None,
    *,
    demo: bool = False,
    dry_run: bool = False,
    today_override: Optional[str] = None,
    quiet: bool = False,
    warn_limit: int = 8,
) -> Dict[str, Any]:
    p = p or util.paths()
    tday = today_override or schema.today()
    taxonomy = util.load_taxonomy(p)

    state_path = _state_path(p)
    prev_state = util.read_json(state_path, default={}) or {}
    report_path = os.path.join(p["root"], "pipeline", ".build-report.json")
    prev_report = util.read_json(report_path, default={}) or {}
    demo_created_ids = set(prev_report.get("demo_created") or [])
    fingerprint = _inputs_fingerprint(p, demo=demo)
    inputs_changed = prev_state.get("fingerprint") != fingerprint

    # --- 1. normalize ----------------------------------------------------
    # `updated` is pipeline-owned.  Bumping it on every run would make the
    # export non-idempotent, so it only moves when the inputs moved.
    if not quiet:
        print(f"[build] {tday}  root {p['root']}")
    norm = normalize.normalize(p, run_date=tday, taxonomy=taxonomy,
                              write=not dry_run, noisy=not quiet)

    # --- 2/3. votes + misses --------------------------------------------
    rows = norm["rows"] if not dry_run else norm["rows"]
    demo_file = os.path.join(p["root"], "data", "demo.votes.json")
    demo_misses = os.path.join(p["root"], "data", "demo.misses.jsonl")
    vote_maps = [votes_mod.load_votes(p["votes"])]
    misses = util.read_jsonl(p["misses"]) if os.path.exists(p["misses"]) else []
    if demo:
        if os.path.exists(demo_file):
            vote_maps.append(seed_votes.load_demo_votes(demo_file))
        elif not quiet:
            print(f"  (--demo: {util.rel(demo_file, p['root'])} not found; "
                  f"run python3 pipeline/seed_votes.py to create it)")
        if os.path.exists(demo_misses):
            misses = misses + util.read_jsonl(demo_misses)
    votes = votes_mod.merge_vote_sources(*vote_maps)
    rows, events = votes_mod.apply_votes(rows, votes, run_date=tday, taxonomy=taxonomy)
    rows, created, skipped = votes_mod.fold_misses(rows, misses, run_date=tday)
    # the fold must never produce an invalid row; report, don't crash the build
    invalid_after = [
        {"id": r["id"], "errors": schema.validate(r, taxonomy=taxonomy, today=tday)}
        for r in rows if schema.validate(r, taxonomy=taxonomy, today=tday)
    ]
    vrep = {
        "run_date": tday, "votes_rows": len(votes), "misses_records": len(misses),
        "promoted": [e for e in events if e["event"] == "promoted"]
        + [{"id": r["id"], "event": "miss-created"} for r in created],
        "orphan_votes": [e for e in events if e["event"] == "vote-orphan"],
        "events": events, "created": created, "miss_skipped": skipped,
        "invalid_after_votes": invalid_after,
        "rows": rows,
    }
    rows = vrep["rows"]

    # A previous `--demo` build may have materialised rows from synthetic
    # votes/misses.  They are not claims: withdraw them on a real build (this is
    # the one sanctioned deletion path; a hand-authored row is never touched).
    if not demo and not dry_run and demo_created_ids:
        keep = []
        for r in rows:
            synthetic = (r["id"] in demo_created_ids
                         and str(r.get("reported_by") or "").startswith(("vote:", "pipeline:miss"))
                         and r.get("created_by") in ("vote", "miss"))
            if not synthetic:
                keep.append(r)
        if len(keep) != len(rows):
            if not quiet:
                print(f"  withdrew {len(rows) - len(keep)} row(s) created by a previous --demo build")
            rows = keep

    # `updated` only advances when the inputs changed (idempotency).
    if not dry_run:
        changed_files = normalize.write_rows(p, rows)
    rows = normalize.load_rows(p) if not dry_run else sorted(rows, key=lambda r: r["id"])

    # --- 4. export -------------------------------------------------------
    previous = util.read_json(p["combos"], default=None)
    # content hash without the volatile fields
    payload = export.next_payload(p, run_date=tday) if not dry_run else None
    if dry_run:
        tax_fields = util.taxonomy_fields(p)
        chash = export.content_hash(rows, tax_fields)
        prev_hash = (previous or {}).get("content_hash")
        if previous and prev_hash == chash and previous.get("rows") == rows:
            version = previous.get("version")
        else:
            base = (previous or {}).get("version") or "0.0"
            try:
                n = int(str(base).rsplit(".", 1)[1])
            except (IndexError, ValueError):
                n = 0
            version = f"{tday}.{n + 1}"
        payload = export.build_payload(rows, tax_fields, version=version, run_date=tday,
                                       generated_at=schema.now(), previous=previous)
    diff = export.diff_summary(previous, payload)
    if demo:
        payload["demo"] = True
    written = {"combos_changed": False, "export_jsonl_changed": False}
    if not dry_run:
        written = export.write_export(p, payload, quiet=quiet)
        util.write_json(state_path, {"fingerprint": fingerprint, "built_at": schema.now(),
                                     "version": payload["version"], "rows": len(rows)})

    # Rows created from real votes/misses are legitimate data and must never be
    # withdrawn.  Only rows a --demo run created (i.e. not backed by a real
    # vote/miss record now) stay on the withdrawal list.
    if not dry_run:
        real_vote_ids = set(votes_mod.load_votes(p["votes"]))
        real_miss_ids = {r["id"] for r in rows if str(r.get("reported_by") or "") == "pipeline:miss-threshold"}
        demo_created_ids = set() if not demo else {
            r["id"] for r in rows
            if str(r.get("reported_by") or "").startswith(("vote:", "pipeline:miss"))
            and r["id"] not in real_vote_ids and r["id"] not in real_miss_ids
        }
    st = stats(rows, rejects=norm["rejects"])
    st["corrections"] = norm.get("corrections", {})
    st.update({
        "version": payload["version"],
        "as_of": payload["as_of"],
        "generated_at": payload["generated_at"],
        "content_changed": bool(diff.get("added") or diff.get("removed") or diff.get("changed")),
        "previous_version": diff.get("previous_version"),
        "changed": {"combos": written["combos_changed"],
                    "export_jsonl": written["export_jsonl_changed"],
                    "row_files": changed_files if not dry_run else 0},
        "diff": diff,
        "votes": {"promoted": len(vrep["promoted"]), "misses": vrep["misses_records"]},
        "inputs_changed": inputs_changed,
        "files": {"rows_dir": p["rows_dir"], "combos": p["combos"],
                  "export_jsonl": p["export_jsonl"]},
        "normalize": {k: norm[k] for k in ("sources", "sources_present", "summary")},
        "rejects": norm["rejects"],
        "warnings": norm["warnings"][:200],
    })
    if not dry_run:
        # demo-created rows are recorded so a non-demo rebuild can withdraw them
        # (they are not claims, and without this a --demo row would be kept
        # forever by the never-delete rule).
        util.write_json(report_path, {
            "demo_created": sorted(demo_created_ids) if demo else [],
            "built_at": payload["generated_at"],
            "version": payload["version"],
            "as_of": payload["as_of"],
            "stats": {k: v for k, v in st.items()},
            "sources": norm["sources"],
            "rejects": norm["rejects"],
            "warnings": norm["warnings"],
        })
    if not quiet:
        print("[build] stats")
        print_stats(st)
        if norm["rejects"]["count"]:
            print(f"  {'rejects':<14} {norm['rejects']['count']} rows refused "
                  f"(see pipeline/.build-report.json)")
            for fp in norm["rejects"]["fingerprints"][:8]:
                print(f"    x{fp['count']:<3} [{fp['source']}] {fp['errors'][0]}")
        print(f"  {'version':<14} {payload['version']}   as_of {payload['as_of']}"
              f"   content changed: {'yes' if st['content_changed'] else 'no'}"
              f"   files written: row-files {st['changed']['row_files']}"
              f" combos {st['changed']['combos']} jsonl {st['changed']['export_jsonl']}")
        if diff.get("previous_version"):
            print(f"  {'diff':<14} vs v{diff['previous_version']}: +{diff['added']} "
                  f"-{diff['removed']} ~{diff['changed']}")
        if vrep["promoted"]:
            print(f"  {'wanted':<14} {len(vrep['promoted'])} rows promoted/created by votes "
                  f"(e.g. {', '.join(e['id'] for e in vrep['promoted'][:3])})")
        for msg, n in list(st.get("corrections", {}).items())[:4]:
            print(f"  corrected x{n:<3} {msg}")
        for w in norm["warnings"][:warn_limit]:
            print(f"  note: {w}")
        if len(norm["warnings"]) > warn_limit:
            print(f"  note: ... {len(norm['warnings']) - warn_limit} more notes "
                  f"(all in pipeline/.build-report.json)")
    return st


def check_idempotent(p: Optional[Mapping[str, str]] = None, *, demo: bool = False) -> Dict[str, Any]:
    """Run build twice; compare combos.json ignoring `generated_at`."""
    p = p or util.paths()
    build(p, demo=demo, quiet=True)
    first = util.read_json(p["combos"], default={}) or {}
    build(p, demo=demo, quiet=True)
    second = util.read_json(p["combos"], default={}) or {}
    a = dict(first); b = dict(second)
    ga = a.pop("generated_at", None); gb = b.pop("generated_at", None)
    same = a == b
    return {"identical_except_generated_at": same, "version_1": first.get("version"),
            "version_2": second.get("version"), "generated_at_1": ga, "generated_at_2": gb,
            "rows_1": len(first.get("rows") or []), "rows_2": len(second.get("rows") or [])}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="build data/combos.json from scrapers/out")
    ap.add_argument("--root", default=None, help="project root (default: repo root)")
    ap.add_argument("--demo", action="store_true", help="fold data/demo.votes.json (synthetic)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--today", default=None, help="override the run date (YYYY-MM-DD)")
    ap.add_argument("--check", action="store_true", help="verify a second run is byte-identical")
    ap.add_argument("--json", action="store_true", help="print stats as JSON on stdout")
    ap.add_argument("--warn-limit", type=int, default=8, help="max warning lines on stdout")
    args = ap.parse_args(argv)
    p = util.paths(args.root)
    if args.today and not schema.parse_date(args.today):
        print(f"--today {args.today!r} is not YYYY-MM-DD", file=sys.stderr)
        return 2
    st = build(p, demo=args.demo, dry_run=args.dry_run, today_override=args.today,
               quiet=args.json, warn_limit=args.warn_limit)
    if args.json:
        printable = {k: v for k, v in st.items() if k not in ("rejects",)}
        print(json.dumps(printable, indent=2, sort_keys=True, default=str))
    if args.check:
        rep = check_idempotent(p, demo=args.demo)
        print(f"[check] second run identical except generated_at: "
              f"{rep['identical_except_generated_at']}  (v{rep['version_1']} -> v{rep['version_2']})")
        if not rep["identical_except_generated_at"]:
            print(f"        rows {rep['rows_1']} -> {rep['rows_2']}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
