"""seed_votes.py -- demo votes + miss reports for exercising the UI.

    python3 pipeline/seed_votes.py            # (re)generate data/demo.votes.json
    python3 pipeline/seed_votes.py --misses   # also append demo lines to data/demo.misses.jsonl
    python3 pipeline/seed_votes.py --clean    # delete the demo files

SAFETY: this never writes data/votes.json or data/misses.jsonl.  Real votes are
owned by the vote service (api/server.py); demo votes live in their own file and
are only folded in when you pass `--demo` to pipeline/build.py.  Every synthetic
voter key starts with "demo:" and every synthetic row id is recorded in
`_meta.demo_rows` so a demo dataset is distinguishable from a real one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import normalize, schema, util
else:
    from . import normalize, schema, util

DEMO_PREFIX = "demo:"
MAX_DEMO_VOTES = 12


def _hash(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:8], 16)


def pick_demo_rows(rows: List[Mapping[str, Any]], limit: int = MAX_DEMO_VOTES) -> List[Mapping[str, Any]]:
    """Deterministically choose rows that need votes: derived/scraped, unsolved."""
    cands = [r for r in rows if r.get("status") != "solved"]
    # prefer rows with no pointer, but a fully solved corpus still demonstrates
    # the age/vote display (a solved row's vote is demand, per votes.py).
    cands.sort(key=lambda r: (bool(r.get("pointer")), r["id"]))
    if not cands:
        cands = list(rows)
    # stable order: by id hash, so the same corpus yields the same demo set
    cands.sort(key=lambda r: (_hash("pick", r["id"]), r["id"]))
    return cands[:limit]


def build_demo(rows: List[Mapping[str, Any]], *, run_date: str,
               votes_path: Optional[str] = None) -> Dict[str, Any]:
    chosen = pick_demo_rows(rows)
    votes: Dict[str, Dict[str, Any]] = {}
    for i, row in enumerate(chosen):
        n = 1 + (_hash("count", row["id"]) % 7)
        requesters = [f"{DEMO_PREFIX}user{h:04d}" for h in
                      sorted({_hash("req", row["id"], str(k)) % 9999 for k in range(n)})]
        first = run_date
        if n >= 4:
            # make one row visibly old so the UI can show age
            first = f"{int(run_date[:4])}-{max(1, int(run_date[5:7]) - 2):02d}-{run_date[8:10]}"
        votes[row["id"]] = {"count": len(requesters),
                            "requesters": requesters[:10], "first": first}
    misses: List[Dict[str, Any]] = []
    if chosen:
        base = chosen[0]
        for k in range(3):
            misses.append({
                "ts": f"{run_date}T0{k + 1}:00:00Z",
                "query": {"hw": base["hw_arch"], "model": "qwen3", "runtime": "vllm",
                          "status": None, "kind": None, "q": None, "limit": 50},
                "query_id": f"demo{k:04d}",
                "searcher_key": f"{DEMO_PREFIX}searcher-{k}",
                "user_agent": "demo/seed_votes",
            })
    # never shadow a real vote: a demo vote on an id that already has real votes
    # would otherwise hide the true count from the export.
    if votes_path:
        for rid, entry in (util.read_json(votes_path, default={}) or {}).items():
            if rid in votes:
                votes.pop(rid, None)
    payload = {
        "_meta": {
            "synthetic": True,
            "generated_at": schema.now(),
            "run_date": run_date,
            "note": "DEMO DATA -- not real votes. Folded only with: python3 pipeline/build.py --demo",
            "demo_rows": sorted(votes),
        },
        "votes": votes,
        "misses": misses,
    }
    return payload


def write_demo(p: Mapping[str, str], *, run_date: Optional[str] = None) -> Dict[str, Any]:
    tday = run_date or schema.today()
    rows = normalize.load_rows(p)
    payload = build_demo(rows, run_date=tday, votes_path=p["votes"])
    votes_doc = dict(payload["votes"])
    votes_path = os.path.join(p["root"], "data", "demo.votes.json")
    misses_path = os.path.join(p["root"], "data", "demo.misses.jsonl")
    util.write_json(votes_path, {"_meta": payload["_meta"], "votes": payload["votes"]})
    with open(misses_path, "w", encoding="utf-8", newline="\n") as fh:
        for m in payload["misses"]:
            fh.write(json.dumps(m, sort_keys=True) + "\n")
    return {"votes_path": votes_path, "misses_path": misses_path,
            "voted_rows": len(votes_doc), "misses": len(payload["misses"]),
            "rows_available": len(rows)}


def clean(p: Mapping[str, str]) -> List[str]:
    removed = []
    for name in ("demo.votes.json", "demo.misses.jsonl"):
        path = os.path.join(p["root"], "data", name)
        if os.path.exists(path):
            os.unlink(path)
            removed.append(path)
    return removed


def load_demo_votes(path: str) -> Dict[str, Dict[str, Any]]:
    """Read data/demo.votes.json -> the plain votes shape {"<id>": {...}}.

    The file carries a `_meta` block (synthetic marker); the vote fold only sees
    the `votes` mapping so a demo build uses exactly the documented shape.
    """
    doc = util.read_json(path, default=None)
    if isinstance(doc, Mapping) and isinstance(doc.get("votes"), Mapping):
        return dict(doc["votes"])
    if isinstance(doc, Mapping):
        return {k: v for k, v in doc.items() if not str(k).startswith("_")}
    return {}


def synthetic_misses(paths: Mapping[str, str], *, n_searchers: int = 3,
                     limit: int = 2) -> List[Dict[str, Any]]:
    """Miss records in the documented data/misses.jsonl shape, for a self-test.

    Deliberately NOT written to data/misses.jsonl (that file is real users'
    evidence); build.py --demo folds them from data/demo.misses.jsonl.
    """
    rows = normalize.load_rows(paths)
    out: List[Dict[str, Any]] = []
    if not rows:
        return out
    hw = rows[0]["hw_arch"]
    for family in sorted({r["model_family"] for r in rows if r["model_family"] != "*"})[:limit]:
        for k in range(n_searchers):
            out.append({
                "ts": f"{schema.today()}T0{k}:00:00Z",
                "query": {"hw": hw, "model": "demo-" + family, "runtime": "vllm",
                          "status": None, "kind": None, "q": None, "limit": 50},
                "query_id": f"demo-{family}-{k}",
                "searcher_key": f"{DEMO_PREFIX}searcher-{family}-{k}",
                "user_agent": "demo/self-test",
            })
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="generate synthetic demo votes/misses")
    ap.add_argument("--root", default=None)
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--today", default=None)
    args = ap.parse_args(argv)
    p = util.paths(args.root)
    if args.clean:
        for f in clean(p):
            print(f"removed {util.rel(f, p['root'])}")
        return 0
    rep = write_demo(p, run_date=args.today)
    print(f"[seed] wrote {util.rel(rep['votes_path'], p['root'])} "
          f"({rep['voted_rows']} demo-voted rows of {rep['rows_available']}) and "
          f"{util.rel(rep['misses_path'], p['root'])} ({rep['misses']} miss records)")
    print("[seed] these are SYNTHETIC. Use them with: python3 pipeline/build.py --demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
