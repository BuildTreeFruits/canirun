#!/usr/bin/env python3
"""Run every scraper source end-to-end and write scrapers/out/<source>.jsonl.

    python3 scrapers/run_all.py                 # live network (per-host 1 req/s), 6h cache TTL
    python3 scrapers/run_all.py --offline       # replay scrapers/cache only, no network
    python3 scrapers/run_all.py --only hf_models
    python3 scrapers/run_all.py --fresh         # ignore cache TTL (live re-fetch, ETag-aware)

Each source appends one line to scrapers/runs.jsonl and writes
scrapers/out/<source>.jsonl + <source>.rejects.json. Rows that fail CONTRACT §1 validation
are refused, never written. Output is sorted by (id, as_of) so re-runs are idempotent.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.common import Http, run_source  # noqa: E402

SOURCES = [
    "llama_cpp_backends",
    "vllm_install",
    "apple_integrations",
    "hf_models",
    "gh_issues",
    "gh_releases",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()

    if args.fresh:
        # tell Http to ignore TTL by zeroing the freshness window
        orig = Http.get

        def get(self, url, *, ttl_s=3600, **kw):
            return orig(self, url, ttl_s=-1, **kw)
        Http.get = get
    if args.offline:
        orig = Http.get

        def get(self, url, **kw):
            kw.pop("ttl_s", None)
            kw.pop("retries", None)
            return orig(self, url, retries=0, **kw)
        Http.get = get

    keys = args.only or SOURCES
    total = 0
    print(f"{'source':22s} {'in':>5s} {'out':>5s} {'rej':>4s}  notes")
    for key in keys:
        mod = importlib.import_module(f"scrapers.sources.{key}")
        rec = run_source(mod, offline=args.offline)
        total += rec["rows_out"]
        note = rec.get("error") or (rec["errors"][0] if rec.get("errors") else "")
        print(f"{key:22s} {rec['rows_in']:5d} {rec['rows_out']:5d} {rec['rejects']:4d}  "
              f"{rec['duration_s']:6.1f}s  {note[:70]}")
    print(f"{'TOTAL':22s} {total:15d}")

    # final self-check on everything written
    from scrapers.validate_raw import validate_file
    bad_total = 0
    for f in sorted((ROOT / "scrapers" / "out").glob("*.jsonl")):
        n, bad = validate_file(f)
        bad_total += len(bad)
        if bad:
            print(f"!! {f.name}: {len(bad)} invalid rows")
    print("validation:", "clean" if bad_total == 0 else f"{bad_total} INVALID")
    return 1 if bad_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
