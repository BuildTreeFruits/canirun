#!/usr/bin/env python3
"""scripts/serve.py -- one command to run the whole site locally.

    python3 scripts/serve.py                 # http://127.0.0.1:8787  +  /api/docs
    python3 scripts/serve.py --port 9000
    python3 scripts/serve.py --demo          # also fold data/demo.votes.json (synthetic votes)
    python3 scripts/serve.py --open          # ...and open a browser
    python3 scripts/serve.py --no-build      # never run the pipeline, serve what is there
    python3 scripts/serve.py --status        # report dataset state, then exit

What it does, in order:
  1. loads web/ + api/ from the project root (no install, no build step, stdlib only)
  2. if data/combos.json is missing (or --rebuild), runs pipeline/build.py
  3. if the pipeline failed, says so loudly and serves anyway -- the API answers
     every route with a well-formed empty dataset + the reason, never a blank page
  4. prints the site URL, the docs URL and the lookup URL, then serves forever

The site itself is web/index.html: it calls /api/lookup first and falls back to
/data/combos.json if the API is unreachable, so the same files also work by
double-clicking index.html from disk.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

DEFAULT_PORT = 8787
DEFAULT_HOST = "127.0.0.1"


def _fmt_bytes(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def dataset_status(data_dir: str) -> dict:
    combos = os.path.join(data_dir, "combos.json")
    out = {"path": combos, "exists": os.path.exists(combos), "rows": 0, "as_of": None,
           "version": None, "size": 0, "error": None}
    if out["exists"]:
        try:
            out["size"] = os.path.getsize(combos)
            with open(combos, encoding="utf-8") as fh:
                blob = json.load(fh)
            out["rows"] = len(blob.get("rows") or [])
            out["as_of"] = blob.get("as_of")
            out["version"] = blob.get("version")
        except (OSError, ValueError) as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def run_pipeline(data_dir: str, demo: bool) -> bool:
    """Run pipeline/build.py. Returns True on success."""
    build_py = os.path.join(ROOT, "pipeline", "build.py")
    if not os.path.exists(build_py):
        print("[serve] pipeline/build.py not found -- skipping the dataset build")
        return False

    # Only pass --root when the data dir is not the project's own data/.
    args = [sys.executable, build_py]
    if os.path.abspath(data_dir) != os.path.abspath(os.path.join(ROOT, "data")):
        args += ["--root", os.path.dirname(os.path.abspath(data_dir))]
    if demo:
        args.append("--demo")
    print(f"[serve] building dataset:  {' '.join(args[1:])}")
    try:
        proc = subprocess.run(args, cwd=ROOT, timeout=300)
    except subprocess.TimeoutExpired:
        print("[serve] build timed out after 300s -- serving what exists", file=sys.stderr)
        return False
    if proc.returncode != 0:
        print(f"[serve] build exited {proc.returncode}; serving what exists. "
              f"The API still answers every route (see /api/health).", file=sys.stderr)
        return False
    return True


def print_banner(host: str, port: int, status: dict) -> None:
    site = f"http://{host}:{port}/"
    print()
    print("  solve.run combo index")
    print("  " + "-" * 56)
    if status["rows"]:
        print(f"  site      {site}")
        print(f"  docs      {site}api/docs            (agent integration: paste one paragraph)")
        print(f"  lookup    {site}api/lookup?hw=sm_86&model=qwen3")
    else:
        print(f"  site      {site}      (no dataset yet -- the page will say so)")
        print(f"  docs      {site}api/docs")
        if status.get("error"):
            print(f"  ! dataset {status['error']}")
    print(f"  dataset   {status['rows']} rows · as_of {status['as_of']} · v{status['version']}"
          f" ({_fmt_bytes(status['size'])})")
    print("  " + "-" * 56)
    print("  Ctrl-C to stop")
    print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="run the combo-index site locally (stdlib only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"),
                    help="dataset directory (default: <project>/data)")
    ap.add_argument("--static-dir", default=os.path.join(ROOT, "web"),
                    help="site directory (default: <project>/web)")
    ap.add_argument("--demo", action="store_true",
                    help="fold data/demo.votes.json (synthetic votes) via the pipeline")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild the dataset even if data/combos.json exists")
    ap.add_argument("--no-build", action="store_true",
                    help="never run the pipeline; serve whatever is on disk")
    ap.add_argument("--status", action="store_true", help="report dataset state and exit")
    ap.add_argument("--open", action="store_true", help="open a browser at the site URL")
    ap.add_argument("--quiet", action="store_true", help="no per-request logging")
    args = ap.parse_args(argv)

    data_dir = os.path.abspath(args.data_dir)
    os.makedirs(data_dir, exist_ok=True)

    status = dataset_status(data_dir)
    if args.status:
        print(json.dumps(status, indent=2))
        return 0 if status["rows"] else 1

    need_build = (not status["exists"]) or status["rows"] == 0 or args.rebuild

    # --demo with an existing export still needs a fold, or the demo votes never show
    if args.demo and not need_build:
        need_build = os.path.exists(os.path.join(ROOT, "data", "demo.votes.json"))

    if need_build and not args.no_build:
        run_pipeline(data_dir, args.demo)
        status = dataset_status(data_dir)
    elif need_build and args.no_build:
        print("[serve] --no-build: not running the pipeline")
    elif args.demo:
        print("[serve] note: --demo given but no data/demo.votes.json to fold "
              "(try: python3 pipeline/seed_votes.py)")

    import server as api_server  # noqa: E402 — after sys.path setup

    if not api_server._port_free(args.host, args.port):
        print(f"[serve] port {args.port} is already in use.\n"
              f"        Something is already there -- try it, or use --port {args.port + 1}.",
              file=sys.stderr)
        return 2

    srv = api_server.make_server(args.host, args.port, data_dir=data_dir,
                                 static_dir=args.static_dir, quiet=args.quiet)
    host, port = srv.server_address[0], srv.server_address[1]
    status = dataset_status(data_dir)
    print_banner(host, port, status)
    sys.stdout.flush()

    if args.open:
        webbrowser.open(f"http://{host}:{port}/")

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] stopped")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
