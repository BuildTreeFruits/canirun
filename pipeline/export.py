"""Export: data/rows/*.jsonl -> data/combos.json + data/export.jsonl

combos.json (CONTRACT §4 "static fallback", §6 taxonomy, task-2 shape):

    {
      "version": "2026-11-22.3",     # <as_of date>.<n>; n increments only when
                                     #   the row content changes
      "generated_at": "...Z",        # clock only -- the one volatile field
      "as_of": "2026-11-22",         # max(updated, as_of) across rows
      "counts":  {"by_status": {...}, "by_vendor": {...},
                  "by_runtime": {...}, "by_source_kind": {...},
                  "by_hw_arch": {...}, "by_model_family": {...}},
      "taxonomy": {"version", "vendors", "runtimes", "models", "quants"},
      "rows":   [ ...full rows, sorted by id... ],
      "wanted": [ ...rows sorted votes desc then want_first asc... ]
    }

Determinism: everything except `generated_at` (and `stats.jsonl`, a separate
after-the-fact log) is a pure function of the row data.  The version is
derived from a content hash, so two runs over unchanged rows produce
byte-identical output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import schema, util
else:
    from . import schema, util

FORMAT_VERSION = "1"


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

def _bump(counter: Dict[str, int], key: Any) -> None:
    k = str(key) if key is not None else "null"
    counter[k] = counter.get(k, 0) + 1


def counts(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, int]]:
    c: Dict[str, Dict[str, int]] = {
        "by_status": {}, "by_vendor": {}, "by_runtime": {},
        "by_source_kind": {}, "by_hw_arch": {}, "by_model_family": {},
        "by_created_by": {},
    }
    for row in rows:
        _bump(c["by_status"], row.get("status"))
        _bump(c["by_vendor"], row.get("hw_vendor"))
        _bump(c["by_runtime"], row.get("runtime"))
        _bump(c["by_source_kind"], row.get("source_kind"))
        _bump(c["by_hw_arch"], row.get("hw_arch"))
        _bump(c["by_model_family"], row.get("model_family"))
        _bump(c["by_created_by"], row.get("created_by"))
    return {k: dict(sorted(v.items())) for k, v in c.items()}


def dataset_as_of(rows: Iterable[Mapping[str, Any]], run_date: str) -> str:
    """The date the dataset speaks for: the latest row date (never future)."""
    best = run_date
    for row in rows:
        for f in ("updated", "as_of"):
            d = row.get(f)
            if schema.parse_date(d) and d > best:
                best = d
    return best


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

def row_sort_key(row: Mapping[str, Any]) -> str:
    return str(row.get("id") or "")


def wanted_sort_key(row: Mapping[str, Any]):
    """CONTRACT: wanted rows sorted votes desc then want_first asc."""
    votes = row.get("want_votes")
    votes = votes if isinstance(votes, int) else 0
    first = row.get("want_first") or "9999-12-31"
    return (-votes, str(first), str(row.get("id") or ""))


def ordered_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = [dict(r) for r in rows]
    out.sort(key=row_sort_key)
    return out


def wanted_rows(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The demand list: every row with votes (status wanted, or solved rows that
    attracted demand -- CONTRACT: a solved row is never downgraded, but the
    interest in it is real and belongs on the wanted board)."""
    out = [dict(r) for r in rows
           if r.get("status") == "untested" or (r.get("want_votes") or 0) > 0]
    out.sort(key=wanted_sort_key)
    return out


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

def content_hash(rows: Iterable[Mapping[str, Any]], taxonomy: Mapping[str, Any]) -> str:
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(row, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    h.update(json.dumps(taxonomy, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Build the payload (pure)
# ---------------------------------------------------------------------------

def build_payload(
    rows: List[Mapping[str, Any]],
    taxonomy: Mapping[str, Any],
    *,
    version: str,
    generated_at: str,
    run_date: str,
    previous: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    rows = ordered_rows(rows)
    tax = taxonomy
    as_of = dataset_as_of(rows, run_date)
    payload = {
        "format": FORMAT_VERSION,
        "contract": "solve.run combo-index v1",
        "version": version,
        "generated_at": generated_at,
        "as_of": as_of,
        "counts": counts(rows),
        "taxonomy": tax,
        "rows": rows,
        "wanted": wanted_rows(rows),
        "content_hash": content_hash(rows, tax),
    }
    return payload


def next_payload(
    p: Mapping[str, str],
    *,
    run_date: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the next combos.json payload, preserving the version when the
    content is unchanged (the deterministic bit)."""
    from pipeline import normalize
    tday = run_date or schema.today()
    rows = normalize.load_rows(p)
    taxonomy = util.taxonomy_fields(p)
    previous = util.read_json(p["combos"], default=None)
    chash = content_hash(rows, taxonomy)

    prev_hash = (previous or {}).get("content_hash")
    prev_version = (previous or {}).get("version") or ""
    if prev_hash is None and previous:  # legacy payload without a hash: repair
        try:
            prev_rows = previous.get("rows") or []
            prev_hash = content_hash(prev_rows, previous.get("taxonomy") or taxonomy)
        except Exception:  # noqa: BLE001 - never fatal for the version scheme
            prev_hash = None

    if previous and prev_hash is not None:
        if prev_hash == chash and previous.get("rows") == rows:
            version = prev_version or f"{tday}.1"
        else:
            base = prev_version or "0.0"
            # n increments; the date part is informational only
            try:
                n = int(base.rsplit(".", 1)[1])
            except (IndexError, ValueError):
                n = 0
            version = f"{tday}.{n + 1}"
    else:
        version = f"{tday}.1"

    payload = build_payload(rows, taxonomy, version=version, run_date=tday,
                            generated_at=generated_at or schema.now(), previous=previous)
    return payload


def diff_summary(previous: Optional[Mapping[str, Any]],
                 payload: Mapping[str, Any]) -> Dict[str, Any]:
    if not previous:
        return {"previous_version": None, "rows": len(payload["rows"]), "added": len(payload["rows"]),
                "removed": 0, "changed": 0}
    old = {r["id"]: r for r in previous.get("rows") or [] if isinstance(r, Mapping) and r.get("id")}
    new = {r["id"]: r for r in payload["rows"]}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(i for i in set(new) & set(old) if old[i] != new[i])
    return {"previous_version": previous.get("version"), "added": len(added),
            "removed": len(removed), "changed": len(changed),
            "added_ids": added[:20], "changed_ids": changed[:40], "removed_ids": removed[:20]}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_export(p: Mapping[str, str], payload: Mapping[str, Any], *, quiet: bool = False) -> Dict[str, Any]:
    changed_combos = util.write_json(p["combos"], payload, indent=2)
    changed_jsonl = util.write_jsonl(p["export_jsonl"], payload["rows"])
    result = {"combos_changed": changed_combos, "export_jsonl_changed": changed_jsonl,
              "combos": p["combos"], "export_jsonl": p["export_jsonl"],
              "bytes": os.path.getsize(p["combos"])}
    if not quiet:
        print(f"[export] {os.path.basename(p['combos'])} v{payload['version']} "
              f"rows {len(payload['rows'])} wanted {len(payload['wanted'])} "
              f"as_of {payload['as_of']} bytes {result['bytes']}"
              f"{'' if changed_combos else ' (unchanged)'}")
    return result


def load_export_rows(p: Mapping[str, str]) -> List[Dict[str, Any]]:
    data = util.read_json(p["combos"], default=None)
    if isinstance(data, Mapping) and isinstance(data.get("rows"), list):
        return [r for r in data["rows"] if isinstance(r, dict)]
    return []


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="export data/rows -> data/combos.json")
    ap.add_argument("--root", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--generated-at", default=None, help="override generated_at (tests)")
    args = ap.parse_args(argv)
    p = util.paths(args.root)
    previous = util.read_json(p["combos"], default=None)
    payload = next_payload(p, generated_at=args.generated_at)
    d = diff_summary(previous, payload)
    print(f"[export] diff vs {d['previous_version']}: +{d['added']} -{d['removed']} ~{d['changed']}")
    if not args.dry_run:
        write_export(p, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
