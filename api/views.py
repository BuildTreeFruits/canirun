"""View builders: turn a store snapshot into the response bodies the API promises.

Kept separate from store.py so the CONTRACT §4 shaping is one small, readable file —
this is the file to read if you want to know exactly what /api/lookup returns.
"""

from __future__ import annotations

from store import (
    DEFAULT_LIMIT, MAX_LIMIT, Dataset, Store, _is_star, _sort_key, _today, _utcnow,
    query_id_for,
)


# --------------------------------------------------------------------------
# CONTRACT §4
# --------------------------------------------------------------------------

def lookup_payload(store: Store, query: dict) -> dict:
    """The CONTRACT §4 response object, key for key."""
    ds = store.dataset()
    body = ds.search(query)
    miss = body["miss"]

    if miss.get("is_miss"):
        _enrich_miss(store, ds, query, miss)

    return {
        "query": query,
        "rows": body["rows"],
        "context": body["context"],
        "miss": miss,
        "query_id": query_id_for(query),
        "generated_at": _utcnow(),
        "dataset": ds.meta(),
    }


def _enrich_miss(store: Store, ds: Dataset, query: dict, miss: dict) -> None:
    """A miss on a combination that is already wanted should say so (known_wanted).

    The export may not have folded a fresh vote yet, so votes that exist only in
    data/votes.json are counted here too.
    """
    matching_wanted = [r for r in ds.rows
                       if r.get("status") == "wanted"
                       and ds.matches(r, query, include_status=False)]
    override = {k: v for k, v in (ds.wanted_override or {}).items()
                if _override_matches(k, query, ds)}

    votes = [int(r.get("want_votes") or 0) for r in matching_wanted]
    votes += [int(v.get("count") or 0) for v in override.values()]
    if not votes:
        return

    miss["known_wanted"] = True
    miss["wanted_votes"] = max(votes)
    firsts = [r.get("want_first") for r in matching_wanted if r.get("want_first")]
    firsts += [v.get("first") for v in override.values() if v.get("first")]
    if firsts and not miss.get("last_checked"):
        miss["last_checked"] = max(firsts)
    if miss["reason"] == "no-match":
        miss["reason"] = "wanted-only"
        miss["hint"] = ds._hint(query, "wanted-only", [], miss["wanted_votes"])


def _override_matches(row_id: str, query: dict, ds: Dataset) -> bool:
    """Can a vote-only id (no export row yet) satisfy this query? Match id segments."""
    parts = row_id.split("/")
    if len(parts) != 4:
        return False
    vendor, arch, family, runtime = parts
    pseudo = {"hw_vendor": vendor, "hw_arch": arch, "model_family": family,
              "runtime": runtime, "status": "wanted", "source_kind": "vote"}
    if query.get("hw") and not ds.match_hw(pseudo, query["hw"]):
        return False
    if query.get("model") and not ds.match_model(pseudo, query["model"]):
        return False
    if query.get("runtime") and not ds.match_runtime(pseudo, query["runtime"]):
        return False
    if query.get("status") and query["status"] != "wanted":
        return False
    if query.get("kind") and query["kind"] != "vote":
        return False
    return True


# --------------------------------------------------------------------------
# wanted / browse
# --------------------------------------------------------------------------

def synthetic_wanted_row(row_id: str, rec: dict) -> dict:
    """A wanted row for a vote whose id the pipeline has not exported yet.

    Marked `unknown_to_export` so a UI can say so rather than pretend it is a
    pipeline-built row.
    """
    parts = (row_id.split("/") + ["", "", "", ""])[:4]
    vendor, arch, family, runtime = parts
    return {
        "id": row_id, "status": "wanted", "source_kind": "vote", "provisional": True,
        "hw_vendor": vendor, "hw_arch": arch, "hw_name": None, "hw_extra": {},
        "model_family": family, "model_rev": None, "quant": None,
        "runtime": runtime, "runtime_rev": None, "pointer": None,
        "notes": "Voted for through /api/want; not yet folded into the export by the pipeline.",
        "measurement": None, "pointer_alive": True, "as_of": _today(),
        "reported_by": "api:vote", "first_seen": rec.get("first") or _today(),
        "updated": _today(), "want_votes": int(rec.get("count") or 0),
        "want_first": rec.get("first"),
        "want_requesters": list(rec.get("requesters") or [])[:10],
        "evidence": [], "missing": ["hw", "model"], "created_by": "vote",
        "unknown_to_export": True,
    }


def wanted_rows(store: Store, query: dict | None = None) -> list[dict]:
    """CONTRACT: wanted rows sorted want_votes desc, then want_first asc."""
    ds = store.dataset()
    rows = [dict(r) for r in ds.rows if r.get("status") == "wanted"]
    for row_id, rec in (ds.wanted_override or {}).items():
        rows.append(synthetic_wanted_row(row_id, rec))
    if query:
        q = dict(query)
        q["status"] = None          # this listing *is* the wanted set
        q["limit"] = MAX_LIMIT
        rows = [r for r in rows if ds.matches(r, q, include_status=False)]
    rows.sort(key=lambda r: (-int(r.get("want_votes") or 0),
                             str(r.get("want_first") or "\uffff"),
                             str(r.get("id") or "")))
    return rows


def browse(store: Store, query: dict, offset: int = 0) -> dict:
    """GET /api/rows — filtered browse; counts cover the whole match set, not the page."""
    ds = store.dataset()
    matched = [row for row in ds.rows if ds.matches(row, query)]
    matched.sort(key=_sort_key)
    limit = query.get("limit") or DEFAULT_LIMIT
    counts = {"total": len(matched), "by_status": {}, "by_vendor": {},
              "by_source_kind": {}}
    for r in matched:
        for bucket, key in (("by_status", "status"), ("by_vendor", "hw_vendor"),
                            ("by_source_kind", "source_kind")):
            v = str(r.get(key) or "?")
            counts[bucket][v] = counts[bucket].get(v, 0) + 1
    return {
        "query": query, "offset": offset, "limit": limit, "counts": counts,
        "dataset": ds.meta(), "rows": matched[offset:offset + limit],
        "generated_at": _utcnow(),
    }
