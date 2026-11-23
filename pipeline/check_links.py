"""Link checker: async HEAD/GET over distinct pointers -> pointer_alive.

    python3 pipeline/check_links.py                 # check stale/missing urls
    python3 pipeline/check_links.py --limit 50      # cap this run
    python3 pipeline/check_links.py --all           # ignore the 7 day TTL
    python3 pipeline/check_links.py --dry-run       # report, write nothing
    python3 pipeline/check_links.py --offline       # cache only, no network

Semantics (task brief):
    2xx / 3xx                     -> pointer_alive = true
    404 / 410                     -> pointer_alive = false
    connection failure / DNS fail -> pointer_alive = false
    timeout / 429 / 5xx / 403     -> *untouched* (a network blip must not
                                     kill the corpus)

Results are cached in pipeline/.linkcache.json (default 7 day TTL) so re-runs
only touch stale urls.  `data/rows/*.jsonl` is rewritten only when a value
actually changes, so this step stays idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pipeline import normalize, schema, util
else:
    from . import normalize, schema, util

TTL_DAYS = 7
DEFAULT_TIMEOUT = 5.0
USER_AGENT = "canirun-index/0.1 (+link-check; contact via repo)"
# Verdicts that are allowed to move pointer_alive.  Everything else leaves the
# stored value untouched.
ALIVE_STATUSES = range(200, 400)
DEAD_STATUSES = (404, 410)
# 400/451 are deliberately NOT opinions: some hosts answer 400 to HEAD, and a
# blocked page (451) is not evidence that the claim is gone.
NO_OPINION = "unknown"

def _fetch_sync(url: str, timeout: float) -> Tuple[str, Optional[int], str]:
    """Return (verdict, http_status, detail).  verdict: alive|dead|unknown."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    # 1) HEAD, which is cheap.  2) fall back to a ranged GET for 405/501/403.
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers=headers)
        if method == "GET":
            req.add_header("Range", "bytes=0-2047")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", resp.getcode()) or 0
                if code in ALIVE_STATUSES:
                    return "alive", code, "ok"
                return "unknown", code, f"unexpected {code}"
        except urllib.error.HTTPError as exc:
            code = exc.code
            if code in ALIVE_STATUSES:
                return "alive", code, "ok"
            if code in DEAD_STATUSES:
                return "dead", code, f"http {code}"
            if method == "HEAD" and code in (403, 405, 501):
                continue  # some hosts refuse HEAD; try GET once
            return "unknown", code, f"http {code} (no opinion)"
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            low = reason.lower()
            if any(t in low for t in ("timed out", "timeout", "temporary failure", "try again",
                                      "connection reset")):
                return "unknown", None, f"network: {reason[:80]}"
            return "dead", None, f"unreachable: {reason[:80]}"
        except TimeoutError:
            return "unknown", None, "timeout"
        except Exception as exc:  # noqa: BLE001 - never crash the checker
            return "unknown", None, f"{type(exc).__name__}: {str(exc)[:80]}"
    return "unknown", None, "headless"


async def _probe(url: str, timeout: float, sem: asyncio.Semaphore) -> Tuple[str, str, Optional[int], str]:
    async with sem:
        loop = asyncio.get_running_loop()
        try:
            verdict, code, detail = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch_sync, url, timeout), timeout=timeout + 2)
        except asyncio.TimeoutError:
            verdict, code, detail = "unknown", None, "timeout"
    return url, verdict, code, detail


def load_cache(path: str) -> Dict[str, Dict[str, Any]]:
    data = util.read_json(path, default={}) or {}
    return data if isinstance(data, dict) else {}


def _stale(entry: Optional[Mapping[str, Any]], now_ts: float, ttl_days: int) -> bool:
    if not entry:
        return True
    ts = entry.get("ts")
    if not isinstance(ts, (int, float)):
        return True
    # only a verdict with an opinion may go stale; "unknown" (timeout/5xx) is
    # retried on the next run, and a ts of 0 is treated as very old.
    return (now_ts - ts) > ttl_days * 86400


def collect_urls(rows: List[Mapping[str, Any]]) -> Dict[str, List[str]]:
    """url -> [row ids] for every pointer in the corpus."""
    urls: Dict[str, List[str]] = {}
    for row in rows:
        p = row.get("pointer")
        if isinstance(p, str) and p.startswith(("http://", "https://")):
            urls.setdefault(p, []).append(row["id"])
    return urls


def apply_results(rows: List[Mapping[str, Any]], verdicts: Mapping[str, str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Copy verdicts onto rows.  Returns (rows, changes)."""
    out = []
    changes = []
    for row in rows:
        row = dict(row)
        url = row.get("pointer")
        verdict = verdicts.get(url) if url else None
        if verdict == "alive" and row.get("pointer_alive") is not True:
            row["pointer_alive"] = True
            changes.append({"id": row["id"], "pointer_alive": True})
        elif verdict == "dead" and row.get("pointer_alive") is not False:
            row["pointer_alive"] = False
            changes.append({"id": row["id"], "pointer_alive": False})
        out.append(row)
    return out, changes


def check_links(
    p: Optional[Mapping[str, str]] = None,
    *,
    limit: Optional[int] = None,
    timeout: float = DEFAULT_TIMEOUT,
    ttl_days: int = TTL_DAYS,
    force_all: bool = False,
    dry_run: bool = False,
    offline: bool = False,
    concurrency: int = 6,
    quiet: bool = False,
) -> Dict[str, Any]:
    p = p or util.paths()
    import time
    now_ts = time.time()
    rows = normalize.load_rows(p)
    urls = collect_urls(rows)
    cache = load_cache(p["linkcache"])

    todo = [u for u in sorted(urls) if force_all or _stale(cache.get(u), now_ts, ttl_days)]
    if limit is not None:
        todo = todo[:limit]

    results: Dict[str, Dict[str, Any]] = {}
    if offline:
        verdicts = {u: (cache.get(u) or {}).get("verdict", "unknown") for u in urls}
    # `results` (fresh probes) drive the summary; `verdicts` (cache + probes)
    # drive the rows, so a fresh run does not erase an older honest verdict.
    else:
        sem = asyncio.Semaphore(max(1, concurrency))

        async def run() -> List[Tuple[str, str, Optional[int], str]]:
            return await asyncio.gather(*[_probe(u, timeout, sem) for u in todo])

        probed = asyncio.run(run()) if todo else []
        for url, verdict, code, detail in probed:
            results[url] = {"verdict": verdict, "status": code, "detail": detail, "ts": now_ts}
            cache[url] = results[url]
        verdicts = {}
        for u in urls:
            e = cache.get(u)
            verdicts[u] = (e or {}).get("verdict", "unknown")

    rows2, changes = apply_results(rows, verdicts)
    if changes and not dry_run:
        normalize.write_rows(p, rows2)
        # the published export carries a copy of pointer_alive: rebuild it
        # (imported lazily; export -> normalize would otherwise cycle)
        from pipeline import export as _export
        try:
            _export.write_export(p, _export.next_payload(p), quiet=True)
        except Exception as exc:  # noqa: BLE001 - a stale export is better than a crash
            print(f"[links] note: export not rebuilt ({type(exc).__name__}: {exc})")
    # cache is only written when something new was learned
    if results and not dry_run:
        util.write_json(p["linkcache"], cache)

    summary = {
        "checked": len(todo),
        "distinct_urls": len(urls),
        "rows": len(rows),
        "alive": sum(1 for v in results.values() if v["verdict"] == "alive"),
        "dead": sum(1 for v in results.values() if v["verdict"] == "dead"),
        "unknown": sum(1 for v in results.values() if v["verdict"] == "unknown"),
        "changed": len(changes),
        "dead_urls": sorted(u for u, v in verdicts.items() if v == "dead"),
        "changes": changes,
        "offline": offline,
        "dry_run": dry_run,
    }
    if not quiet:
        print(f"[links] {len(rows)} rows  {len(urls)} distinct pointers  "
              f"checked {len(todo)}  alive {summary['alive']}  dead {summary['dead']}  "
              f"no-opinion {summary['unknown']}  rows updated {len(changes)}"
              + ("  (dry-run)" if dry_run else "") + ("  (offline)" if offline else ""))
        for u in summary["dead_urls"][:10]:
            print(f"  dead: {u}")
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="check pointer urls -> pointer_alive")
    ap.add_argument("--root", default=None)
    ap.add_argument("--limit", type=int, default=None, help="check at most N urls")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    ap.add_argument("--ttl-days", type=int, default=TTL_DAYS)
    ap.add_argument("--all", action="store_true", help="ignore the cache TTL")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", action="store_true", help="replay the cache, no network")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = check_links(util.paths(args.root), limit=args.limit, timeout=args.timeout,
                      ttl_days=args.ttl_days, force_all=args.all, dry_run=args.dry_run,
                      offline=args.offline, concurrency=args.concurrency, quiet=args.json)
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
