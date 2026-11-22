"""Validate raw scraper rows against CONTRACT.md §1/§2 invariants.

Enforces the contract as written; a row that fails is refused (logged into
scrapers/out/<source>.rejects.json) and never written to the jsonl.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_T = json.loads((ROOT / "data" / "taxonomy.json").read_text())
VENDORS = set(_T["hw_vendors"])
RUNTIMES = {r["slug"] for r in _T["runtimes"]}
STATUSES = {"solved", "wanted", "rejected"}
KINDS = {"scraped", "derived", "hand", "author-claim"}
EV_KINDS = {"upstream-doc", "package-table", "model-repo", "release", "issue", "community"}
CREATED_BY = {"scraper", "derived", "hand", "vote", "miss"}
REQUIRED = ["id", "status", "source_kind", "hw_vendor", "hw_arch", "model_family",
            "runtime", "as_of", "reported_by", "pointer_alive", "want_votes",
            "want_first", "want_requesters", "evidence"]
BANNED_REV = {"latest", "master", "main", "HEAD", ""}
ID_SEG = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


def _slug(seg: str) -> bool:
    return bool(ID_SEG.match(seg))


def validate(row: dict, today: str | None = None) -> list[str]:
    e: list[str] = []
    for k in REQUIRED:
        if k not in row:
            e.append(f"missing required field {k}")
    if e:
        return e
    today = today or _dt.date.today().isoformat()

    # enums
    if row["status"] not in STATUSES:
        e.append(f"bad status {row['status']!r}")
    if row["status"] == "not-searched":
        e.append("status not-searched is never stored")
    if row["source_kind"] not in KINDS:
        e.append(f"bad source_kind {row['source_kind']!r}")
    if row["hw_vendor"] not in VENDORS:
        e.append(f"bad hw_vendor {row['hw_vendor']!r}")
    if row["runtime"] not in RUNTIMES:
        e.append(f"runtime {row['runtime']!r} not in taxonomy runtimes")
    if "created_by" in row and row["created_by"] not in CREATED_BY:
        e.append(f"bad created_by {row['created_by']!r}")

    # dates
    if not isinstance(row["as_of"], str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", row["as_of"]):
        e.append("as_of not YYYY-MM-DD")
    elif row["as_of"] > today:
        e.append(f"as_of {row['as_of']} is in the future (today {today})")

    # invariant 1..3
    if row["status"] == "solved" and not row.get("pointer"):
        e.append("solved needs pointer")
    # invariant 3 (literal reading: *every* derived row states what it lacks). The CONTRACT
    # §1 example and §3 both show derived + missing:["model"], so we enforce "derived => missing
    # non-empty" for all derived rows, not just those that are also non-'scraped'.
    if row["source_kind"] == "scraped":
        if not row.get("pointer"):
            e.append("scraped needs pointer")
        miss = list(row.get("missing") or [])
        # inv 2 (amended 2026-11-22): complete == missing==[] OR missing==["model"] for a `*` row
        if not (len(miss) == 0 or (miss == ["model"] and row.get("model_family") == "*")):
            e.append(f"scraped must be complete: missing {miss} != [] and != ['model'] with model_family '*'")
    if row["source_kind"] == "derived" and len(row.get("missing") or []) < 1:
        e.append("derived needs >=1 missing[]")
    # hw_arch is a required field, so a derived row that only lacks the model dimension
    # declares that with missing:["model"] (CONTRACT §1 example / §3); the other honest
    # shape for hw-only claims is missing:["hw"]. Anything else is a modelling mistake.
    if row["source_kind"] == "derived" and row.get("missing") and not (
            set(row["missing"]) <= {"hw", "model"} or set(row["missing"]) & {"hw", "model"}):
        e.append(f"derived missing[] {row['missing']} names no dimension")
    # invariant 4
    if row["status"] == "wanted":
        if not (isinstance(row.get("want_votes"), int) and row["want_votes"] >= 1):
            e.append("wanted needs want_votes>=1")
        if not row.get("want_first"):
            e.append("wanted needs want_first")
    else:
        if row.get("want_first") is not None:
            e.append("want_first must be null unless status=wanted")
    if isinstance(row.get("want_votes"), int) and row["want_votes"] < 0:
        e.append("want_votes < 0")
    # invariant 5
    if row["status"] == "rejected" and not row.get("notes"):
        e.append("rejected needs notes (why it fails)")
    # invariant 6
    rr = row.get("runtime_rev")
    if rr is not None and (not isinstance(rr, str) or rr.strip() in BANNED_REV):
        e.append(f"runtime_rev {rr!r} banned (never latest/master/main/HEAD/empty)")

    # id / invariant 8
    segs = [row["hw_vendor"], row["hw_arch"], row["model_family"], row["runtime"]]
    norm = [str(s).lower().replace(".", "_") for s in segs]
    bad = [orig for orig, n in zip(segs, norm)
           if not (n == "*" or _slug(n)) or (n != "*" and "_" in n and "__" in n)]
    if bad:
        e.append(f"id segments not slug-clean: {bad}")
    # CONTRACT §2 as corrected by lead: dots are not allowed in id segments; "." -> "_".
    want = "/".join(str(s).lower().replace(".", "_") for s in segs)
    if row["id"] != want:
        e.append(f"id {row['id']!r} != canonical {want!r}")
    if row["hw_arch"] != row["hw_arch"].lower() and row["hw_arch"] != "*":
        e.append("hw_arch not lowercase")
    if row["model_family"] != row["model_family"].lower():
        e.append("model_family not lowercase")
    # inv 9 (amended 2026-11-22): any `*` row declares the model dimension it omits.
    if row["model_family"] == "*" and "model" not in (row.get("missing") or []):
        e.append("model_family '*' requires missing['model'] (inv 9)")

    # evidence
    ev = row.get("evidence")
    if not isinstance(ev, list) or len(ev) < 1:
        e.append("evidence must be non-empty list")
    else:
        for i, x in enumerate(ev):
            if not isinstance(x, dict):
                e.append(f"evidence[{i}] not object")
                continue
            if not x.get("url") or not str(x["url"]).startswith("http"):
                e.append(f"evidence[{i}] url missing/not http")
            if not x.get("quote") or not str(x["quote"]).strip():
                e.append(f"evidence[{i}] quote empty")
            if x.get("kind") not in EV_KINDS:
                e.append(f"evidence[{i}] kind {x.get('kind')!r} not allowed")

    if not isinstance(row.get("want_requesters"), list):
        e.append("want_requesters must be list")
    if not isinstance(row.get("pointer_alive"), bool):
        e.append("pointer_alive must be bool")
    hj = row.get("hw_extra", {})
    if not isinstance(hj, dict):
        e.append("hw_extra must be object")
    ms = row.get("measurement")
    if ms is not None and not isinstance(ms, dict):
        e.append("measurement must be object or null")
    return e


def validate_file(path: Path) -> tuple[int, list[dict]]:
    n, bad = 0, []
    for i, line in enumerate(path.open(), 1):
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            row = json.loads(line)
        except Exception as ex:  # noqa: BLE001
            bad.append({"line": i, "errors": [f"bad json: {ex}"]})
            continue
        errs = validate(row)
        if errs:
            bad.append({"line": i, "id": row.get("id"), "errors": errs})
    return n, bad


if __name__ == "__main__":
    import sys
    total_bad = 0
    for f in sorted((ROOT / "scrapers" / "out").glob("*.jsonl")):
        n, bad = validate_file(f)
        total_bad += len(bad)
        print(f"{f.name:28s} rows={n:4d} invalid={len(bad)}")
        for b in bad[:5]:
            print("   ", b)
    print("TOTAL INVALID:", total_bad)
    sys.exit(1 if total_bad else 0)
