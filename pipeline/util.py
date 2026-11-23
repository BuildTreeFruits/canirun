"""Pipeline utilities: paths, taxonomy loading, deterministic JSON I/O.

Dependency-free (stdlib only).  Every writer in this package goes through
``write_json`` / ``write_jsonl`` so that byte output is deterministic:
keys are sorted (except where a deliberate order is requested), no
indentation surprises, ``\\n`` line endings, a trailing newline.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional

# repo root = the directory holding this package
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_PATHS = {
    "root": ROOT,
    "scrapers_out": os.path.join(ROOT, "scrapers", "out"),
    "rows_dir": os.path.join(ROOT, "data", "rows"),
    "taxonomy": os.path.join(ROOT, "data", "taxonomy.json"),
    "taxonomy_ext": os.path.join(ROOT, "data", "taxonomy.extensions.json"),
    "votes": os.path.join(ROOT, "data", "votes.json"),
    "misses": os.path.join(ROOT, "data", "misses.jsonl"),
    "combos": os.path.join(ROOT, "data", "combos.json"),
    "export_jsonl": os.path.join(ROOT, "data", "export.jsonl"),
    "linkcache": os.path.join(ROOT, "pipeline", ".linkcache.json"),
}

# Directory names inside data/ that are NOT row files (kept for clarity).
NON_ROW_FILES = {"combos.json", "export.jsonl", "votes.json", "misses.jsonl",
                 "taxonomy.json", "taxonomy.extensions.json"}


def paths(root: Optional[str] = None, **overrides: str) -> Dict[str, str]:
    """Return the path table, optionally rooted somewhere else (for tests)."""
    p = dict(DEFAULT_PATHS)
    if root:
        root = os.path.abspath(root)
        p.update({
            "root": root,
            "scrapers_out": os.path.join(root, "scrapers", "out"),
            "rows_dir": os.path.join(root, "data", "rows"),
            "taxonomy": os.path.join(root, "data", "taxonomy.json"),
            "taxonomy_ext": os.path.join(root, "data", "taxonomy.extensions.json"),
            "votes": os.path.join(root, "data", "votes.json"),
            "misses": os.path.join(root, "data", "misses.jsonl"),
            "combos": os.path.join(root, "data", "combos.json"),
            "export_jsonl": os.path.join(root, "data", "export.jsonl"),
            "linkcache": os.path.join(root, "pipeline", ".linkcache.json"),
        })
    p.update({k: os.path.abspath(v) for k, v in overrides.items()})
    return p


def rel(path: str, root: Optional[str] = None) -> str:
    """Path relative to the repo root, for terse log lines."""
    root = root or ROOT
    try:
        r = os.path.relpath(path, root)
    except ValueError:  # different drive on Windows
        return path
    return r


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def ensure_dir(path: str) -> None:
    d = path if path.endswith(os.sep) or os.path.isdir(path) else os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON ({exc})") from exc


def read_jsonl(path: str) -> List[Any]:
    """Read a JSONL file; blank lines skipped, a malformed line raises."""
    out: List[Any] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{lineno}: invalid JSON ({exc})") from exc
    except FileNotFoundError:
        return []
    return out


def dumps(obj: Any, *, indent: Optional[int] = None, sort_keys: bool = True) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=sort_keys,
                      separators=(",", ": ") if indent else (",", ":"))


def _atomic_write(path: str, data: str) -> None:
    ensure_dir(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: str, obj: Any, *, indent: Optional[int] = None,
               sort_keys: bool = True, trailing_newline: bool = True) -> bool:
    """Atomically write JSON.  Returns True iff the file content changed.

    Idempotency: if the serialised bytes already match the file, nothing is
    written and False is returned.
    """
    data = dumps(obj, indent=indent, sort_keys=sort_keys)
    if trailing_newline:
        data += "\n"
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            if fh.read() == data:
                return False
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    _atomic_write(path, data)
    return True


def write_jsonl(path: str, rows: Iterable[Mapping[str, Any]]) -> bool:
    """Atomically write JSONL (one compact object per line).  Returns changed?"""
    data = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")) + "\n" for r in rows)
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            if fh.read() == data:
                return False
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    _atomic_write(path, data)
    return True


# ---------------------------------------------------------------------------
# Taxonomy (§6) + scraper extensions
# ---------------------------------------------------------------------------

def merge_taxonomy(base: Mapping[str, Any], ext: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge data/taxonomy.extensions.json into the base taxonomy (in memory).

    Extension shape (written by scraper agents):
        {"models": [{"family": ..., "label": ..., "aliases": [...]}, ...],
         "hw_archs": {"nvidia": ["sm_xx", ...], ...},
         "runtimes": [{"slug": ...}], "quants": [...]}

    Base entries win on conflict; extensions may only append.  Returns a new
    dict (input is not mutated).  ``merged_extensions`` lists what was added.
    """
    tax = json.loads(json.dumps(base))  # deep copy, portable
    added = {"models": [], "hw_archs": [], "runtimes": [], "quants": []}
    if not isinstance(ext, Mapping):
        tax["merged_extensions"] = added
        return tax

    models = tax.setdefault("models", [])
    known = {m.get("family") for m in models if isinstance(m, Mapping)}
    for m in ext.get("models") or []:
        if isinstance(m, str):
            m = {"family": m}
        if not isinstance(m, Mapping):
            continue
        fam = m.get("family")
        if not fam:
            continue
        if fam in known:
            # append any *new* aliases to the existing entry
            tgt = next(x for x in models if isinstance(x, Mapping) and x.get("family") == fam)
            aliases = list(tgt.get("aliases") or [])
            for a in m.get("aliases") or []:
                if a not in aliases:
                    aliases.append(a)
            if aliases:
                tgt["aliases"] = aliases
            continue
        entry = {"family": fam, "label": m.get("label") or fam,
                 "aliases": list(m.get("aliases") or []),
                 "vendor": m.get("vendor") or (m.get("source") or "extension")}
        models.append(entry)
        known.add(fam)
        added["models"].append(fam)

    hw_archs = tax.setdefault("hw_archs", {})
    for vendor, archs in (ext.get("hw_archs") or {}).items():
        if isinstance(archs, str):
            archs = [archs]
        cur = hw_archs.setdefault(vendor, [])
        for a in archs or []:
            if a not in cur:
                cur.append(a)
                added["hw_archs"].append(f"{vendor}:{a}")

    runtimes = tax.setdefault("runtimes", [])
    known_rt = {r.get("slug") for r in runtimes if isinstance(r, Mapping)}
    for r in ext.get("runtimes") or []:
        if isinstance(r, str):
            r = {"slug": r}
        if isinstance(r, Mapping) and r.get("slug") and r["slug"] not in known_rt:
            runtimes.append({"slug": r["slug"], "label": r.get("label") or r["slug"],
                             "family": r.get("family") or "any",
                             "repo": r.get("repo"), "docs": r.get("docs")})
            known_rt.add(r["slug"])
            added["runtimes"].append(r["slug"])

    quants = tax.setdefault("quants", [])
    for q in ext.get("quants") or []:
        if q not in quants:
            quants.append(q)
            added["quants"].append(q)

    tax["merged_extensions"] = added
    return tax


def load_taxonomy(p: Mapping[str, str]) -> Dict[str, Any]:
    """Load data/taxonomy.json and merge data/taxonomy.extensions.json."""
    base = read_json(p["taxonomy"], default=None)
    if base is None:
        raise FileNotFoundError(f"taxonomy not found at {p['taxonomy']} -- lead owns this file")
    ext = read_json(p["taxonomy_ext"], default=None)
    return merge_taxonomy(base, ext)


def taxonomy_fields(p: Mapping[str, str]) -> Dict[str, Any]:
    """Compact taxonomy slice used in combos.json (CONTRACT §6 + export shape)."""
    tax = load_taxonomy(p)
    vendors = {}
    for slug, meta in (tax.get("hw_vendors") or {}).items():
        meta = meta if isinstance(meta, Mapping) else {}
        vendors[slug] = {"label": meta.get("label") or slug,
                         "arch_kind": meta.get("arch_kind"),
                         "arch_prefix": meta.get("arch_prefix", ""),
                         "hw_archs": list((tax.get("hw_archs") or {}).get(slug) or [])}
    runtimes = [{"slug": r.get("slug"), "label": r.get("label") or r.get("slug"),
                 "family": r.get("family"), "repo": r.get("repo"), "docs": r.get("docs")}
                for r in (tax.get("runtimes") or []) if isinstance(r, Mapping) and r.get("slug")]
    models = [{"family": m.get("family"), "label": m.get("label") or m.get("family"),
               "aliases": list(m.get("aliases") or []), "vendor": m.get("vendor")}
              for m in (tax.get("models") or []) if isinstance(m, Mapping) and m.get("family")]
    return {"version": tax.get("version"), "vendors": vendors, "runtimes": runtimes,
            "models": models, "quants": list(tax.get("quants") or [])}


__all__ = [
    "ROOT", "DEFAULT_PATHS", "paths", "rel", "ensure_dir", "read_json", "read_jsonl",
    "dumps", "write_json", "write_jsonl", "merge_taxonomy", "load_taxonomy",
    "taxonomy_fields",
]
