#!/usr/bin/env python3
"""Ingest a hardware x model x runtime combo row (and optional taxonomy entry).

Stdlib-only CLI around pipeline.schema.canonicalize() and validate().
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.schema import (  # noqa: E402
    BASIS_VALUES,
    EVIDENCE_KINDS,
    STATUSES,
    canonicalize,
    today,
    validate,
)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate and ingest a combo row (and optional taxonomy arch/aliases)."
    )
    p.add_argument("--vendor", required=True, help="Hardware vendor (e.g. nvidia, apple, amd)")
    p.add_argument("--arch", required=True, help="Hardware architecture slug (e.g. m4-ultra, sm_89)")
    p.add_argument("--hw-name", default=None, help="Human-readable hardware name")
    p.add_argument("--hw-extra", default=None, help="Extra hardware specs/notes")
    p.add_argument("--model", required=True, help="Model family slug (e.g. qwen3, llama-3.1, *)")
    p.add_argument("--runtime", required=True, help="Runtime slug (e.g. mlx-lm, llama.cpp, vllm)")
    p.add_argument("--status", required=True, choices=STATUSES, help="Combo status")
    p.add_argument("--basis", choices=BASIS_VALUES, default=None, help="Basis for untested status")
    p.add_argument("--basis-note", default=None, help="Optional note for basis")
    p.add_argument("--quant", default=None, help="Quantization knob (e.g. Q4_K_M, mlx-4bit)")
    p.add_argument("--context-length", type=int, default=None, help="Context length knob")
    p.add_argument("--offload", default=None, help="Offload knob (e.g. ngl=99)")
    p.add_argument("--runtime-version", default=None, help="Runtime version knob")
    p.add_argument("--driver-version", default=None, help="Driver version knob")
    p.add_argument("--flags", default=None, help="Flags knob")
    p.add_argument("--fits", nargs="*", default=None, help="Fits tags")
    p.add_argument("--pointer", default=None, help="Evidence pointer URL")
    p.add_argument("--quote", default=None, help="Verbatim evidence quote")
    p.add_argument(
        "--evidence-kind",
        choices=EVIDENCE_KINDS,
        default="upstream-doc",
        help="Evidence kind (default: upstream-doc)",
    )
    p.add_argument("--notes", default=None, help="Notes / explanation")
    p.add_argument("--reported-by", default="hand", help="Reporter handle or 'hand'")
    p.add_argument(
        "--register-taxonomy",
        action="store_true",
        help="Register --arch (and --alias) if not already in data/taxonomy.json",
    )
    p.add_argument(
        "--write-taxonomy",
        action="store_true",
        help="Write taxonomy updates directly to data/taxonomy.json instead of data/taxonomy.extensions.json",
    )
    p.add_argument(
        "--alias",
        action="append",
        default=[],
        help="Search alias mapping to --arch (repeatable)",
    )
    p.add_argument("--dry-run", action="store_true", help="Validate and print without writing files")
    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    taxonomy_path = REPO_ROOT / "data" / "taxonomy.json"
    extensions_path = REPO_ROOT / "data" / "taxonomy.extensions.json"
    taxonomy = _load_json(taxonomy_path)
    effective_taxonomy = copy.deepcopy(taxonomy)

    taxonomy_updated = False
    target_tax_path = taxonomy_path if args.write_taxonomy else extensions_path
    target_tax = _load_json(target_tax_path) if target_tax_path.exists() else {}

    if args.register_taxonomy:
        arches = effective_taxonomy.setdefault("hw_archs", {}).setdefault(args.vendor, [])
        if args.arch not in arches:
            arches.append(args.arch)
            t_arches = target_tax.setdefault("hw_archs", {}).setdefault(args.vendor, [])
            if args.arch not in t_arches:
                t_arches.append(args.arch)
            taxonomy_updated = True
        for alias in args.alias:
            alias_key = alias.strip().lower()
            if alias_key and effective_taxonomy.setdefault("hw_aliases", {}).get(alias_key) != args.arch:
                effective_taxonomy["hw_aliases"][alias_key] = args.arch
                target_tax.setdefault("hw_aliases", {})[alias_key] = args.arch
                taxonomy_updated = True

    raw: Dict[str, Any] = {
        "status": args.status,
        "source_kind": "hand",
        "hw_vendor": args.vendor,
        "hw_arch": args.arch,
        "model_family": args.model,
        "runtime": args.runtime,
        "as_of": today(),
        "first_seen": today(),
        "updated": today(),
        "reported_by": args.reported_by,
        "pointer": args.pointer,
        "pointer_alive": True if args.pointer else None,
        "notes": args.notes,
    }
    if args.hw_name:
        raw["hw_name"] = args.hw_name
    if args.hw_extra:
        raw["hw_extra"] = args.hw_extra
    if args.basis:
        raw["basis"] = args.basis
    if args.basis_note:
        raw["basis_note"] = args.basis_note
    if args.quant:
        raw["quant"] = args.quant
    if args.context_length is not None:
        raw["context_length"] = args.context_length
    if args.offload:
        raw["offload"] = args.offload
    if args.runtime_version:
        raw["runtime_version"] = args.runtime_version
    if args.driver_version:
        raw["driver_version"] = args.driver_version
    if args.flags:
        raw["flags"] = args.flags
    if args.fits:
        raw["fits"] = args.fits
    if args.pointer and args.quote:
        raw["evidence"] = [
            {
                "url": args.pointer,
                "quote": args.quote,
                "kind": args.evidence_kind,
            }
        ]

    row = canonicalize(raw, source_key="hand")
    errors = validate(row, taxonomy=effective_taxonomy)
    if errors:
        print("Validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    rows_path = REPO_ROOT / "data" / "rows" / f"{args.vendor}.jsonl"
    if args.dry_run:
        print(f"[dry-run] Validated row: {row['id']}")
        if taxonomy_updated:
            print(f"[dry-run] Would update taxonomy in: {target_tax_path}")
        print(f"[dry-run] Would merge into: {rows_path}")
        print(json.dumps(row, indent=2, ensure_ascii=False))
        return 0

    if taxonomy_updated:
        _write_json(target_tax_path, target_tax)
        print(f"Updated taxonomy: {target_tax_path}")

    existing = _load_jsonl(rows_path)
    by_id = {r["id"]: r for r in existing if "id" in r}
    by_id[row["id"]] = row
    merged = [by_id[k] for k in sorted(by_id)]
    _write_jsonl(rows_path, merged)
    print(f"Wrote {row['id']} to {rows_path} ({len(merged)} total rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
