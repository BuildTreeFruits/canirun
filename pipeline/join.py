"""Model x hardware join for a narrow, verifiable slice.

Joins HF model x runtime quant artifact rows (which carry `model_rev`,
`quant`, and quant filenames) with solved hardware x runtime `*` rows.
Emits `source_kind: "derived"` rows:
  - `missing: []` (with `markers_complete: True`) ONLY where an upstream
    doc or issue actually links that model family to that hardware arch.
  - `missing: ["model", "hw-model-link"]` (partial) everywhere else.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

if __package__ in (None, ""):
    import schema
else:
    from . import schema

JOIN_MODEL_FAMILIES: Tuple[str, ...] = (
    "qwen3",
    "llama-3",
    "mistral",
    "gemma-3",
    "deepseek",
)


def _row_key(row: Mapping[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(row.get("hw_vendor") or ""),
        str(row.get("hw_arch") or ""),
        str(row.get("model_family") or ""),
        str(row.get("runtime") or ""),
    )


def _upstream_linked_keys(rows: Iterable[Mapping[str, Any]]) -> Set[Tuple[str, str, str, str]]:
    """Return (hw_vendor, hw_arch, model_family, runtime) keys explicitly
    linked by an upstream doc or issue (non-star, non-derived rows)."""
    linked: Set[Tuple[str, str, str, str]] = set()
    for r in rows:
        if r.get("model_family") == "*":
            continue
        if r.get("source_kind") == "derived":
            continue
        ev_kinds = {e.get("kind") for e in (r.get("evidence") or []) if isinstance(e, Mapping)}
        if ev_kinds & {"upstream-doc", "issue", "release", "package-table"}:
            linked.add(_row_key(r))
    return linked


def build_join_rows(
    rows: List[Dict[str, Any]],
    *,
    run_date: Optional[str] = None,
    families: Iterable[str] = JOIN_MODEL_FAMILIES,
) -> List[Dict[str, Any]]:
    """Build derived model x hardware join rows for `families`.

    Existing non-derived rows with the same canonical id are never
    overwritten.
    """
    tday = run_date or schema.today()
    target_families = set(families)
    existing_non_derived_ids = {
        r["id"] for r in rows if r.get("source_kind") != "derived"
    }
    linked_keys = _upstream_linked_keys(rows)

    hf_models = [
        r for r in rows
        if r.get("reported_by") == "scraper:hf_models"
        and r.get("model_family") in target_families
        and r.get("model_rev")
    ]
    hw_stars = [
        r for r in rows
        if r.get("model_family") == "*"
        and r.get("status") == "solved"
    ]

    derived: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for m in hf_models:
        for hw in hw_stars:
            if m.get("runtime") != hw.get("runtime"):
                continue
            cid = schema.derive_id(
                hw["hw_vendor"], hw["hw_arch"], m["model_family"], m["runtime"]
            )
            if cid in existing_non_derived_ids or cid in seen_ids:
                continue
            seen_ids.add(cid)

            key = (hw["hw_vendor"], hw["hw_arch"], m["model_family"], m["runtime"])
            is_linked = key in linked_keys

            m_extra = m.get("hw_extra") or {}
            hw_extra = dict(hw.get("hw_extra") or {})
            if m_extra.get("repo"):
                hw_extra["hf_repo"] = m_extra["repo"]
            if m_extra.get("file"):
                hw_extra["quant_file"] = m_extra["file"]

            evidence = list(hw.get("evidence") or [])[:2] + list(m.get("evidence") or [])[:2]

            raw_row: Dict[str, Any] = {
                "id": cid,
                "status": "solved",
                "source_kind": "derived",
                "provisional": False,
                "hw_vendor": hw["hw_vendor"],
                "hw_arch": hw["hw_arch"],
                "hw_name": hw.get("hw_name"),
                "hw_extra": hw_extra,
                "model_family": m["model_family"],
                "model_rev": m.get("model_rev"),
                "quant": m.get("quant"),
                "runtime": m["runtime"],
                "runtime_rev": hw.get("runtime_rev"),
                "pointer": hw.get("pointer") or m.get("pointer"),
                "notes": (
                    f"Joined {m['model_family']} ({m.get('quant') or 'quant'}, rev {str(m.get('model_rev'))[:8]}) "
                    f"with {hw['hw_vendor']}/{hw['hw_arch']} on {m['runtime']}; "
                    + ("upstream doc links model and hardware." if is_linked
                       else "no upstream doc or issue links this model to this card yet (partial).")
                ),
                "measurement": None,
                "pointer_alive": bool(hw.get("pointer_alive", True)),
                "as_of": tday,
                "reported_by": "pipeline:model_hw_join",
                "first_seen": tday,
                "updated": tday,
                "want_votes": 0,
                "want_first": None,
                "want_requesters": [],
                "evidence": evidence,
                "missing": [] if is_linked else ["hw-model-link"],
                "markers_complete": is_linked,
                "created_by": "derived",
            }
            derived.append(schema.canonicalize(raw_row, today=tday, run_date=tday))

    return derived


def apply_join(
    rows: List[Dict[str, Any]],
    *,
    run_date: Optional[str] = None,
    families: Iterable[str] = JOIN_MODEL_FAMILIES,
) -> List[Dict[str, Any]]:
    """Return `rows` with derived model x hardware join rows merged in."""
    joined = build_join_rows(rows, run_date=run_date, families=families)
    if not joined:
        return rows
    by_id: Dict[str, Dict[str, Any]] = {r["id"]: r for r in rows}
    for r in joined:
        if r["id"] not in by_id:
            by_id[r["id"]] = r
    return sorted(by_id.values(), key=lambda r: r["id"])
