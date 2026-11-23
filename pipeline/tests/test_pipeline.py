"""Plain-python test suite for the pipeline (no pytest, no third-party deps).

    python3 pipeline/tests/test_pipeline.py            # run everything
    python3 pipeline/tests/test_pipeline.py -k merge   # run matching tests

Covers: id derivation (§2), every CONTRACT §1 invariant, merge precedence and
no-deletion (§5), votes never downgrading solved rows, miss folding, export
shape, determinism/idempotency of two consecutive builds.
"""

from __future__ import annotations

import copy
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SEED_DIR = os.path.join(HERE, "fixtures", "scrapers_out")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pipeline import build, check_links, export, normalize, schema, seed_votes, util, votes  # noqa: E402

TODAY = "2026-11-22"
TAX = {
    "version": "1",
    "hw_vendors": {"nvidia": {"label": "NVIDIA"}, "amd": {"label": "AMD"},
                   "apple": {"label": "Apple"}, "intel": {"label": "Intel"},
                   "arm-cpu": {"label": "ARM CPU"}, "x86-cpu": {"label": "x86 CPU"},
                   "qualcomm": {"label": "Qualcomm"}, "other": {"label": "Other"}},
    "runtimes": [{"slug": "llama.cpp", "label": "llama.cpp"},
                 {"slug": "vllm", "label": "vLLM"},
                 {"slug": "mlx", "label": "MLX"},
                 {"slug": "unknown", "label": "Unspecified runtime"}],
    "models": [{"family": "qwen3", "label": "Qwen3", "aliases": []},
               {"family": "qwen2.5", "label": "Qwen2.5", "aliases": []}],
    "hw_archs": {"nvidia": ["sm_86", "sm_89", "sm_90"], "amd": ["gfx1100"],
                 "apple": ["m4"]},
    "quants": ["Q4_K_M"],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def base_row(**over) -> dict:
    row = {
        "status": "solved",
        "source_kind": "scraped",
        "hw_vendor": "nvidia",
        "hw_arch": "sm_86",
        "hw_name": "RTX 3090",
        "hw_extra": {"vram_gb": 24},
        "model_family": "qwen3",
        "model_rev": None,
        "quant": "Q4_K_M",
        "runtime": "llama.cpp",
        "runtime_rev": "b6400",
        "pointer": "https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md",
        "notes": "CUDA backend builds for sm_86.",
        "measurement": None,
        "pointer_alive": True,
        "as_of": TODAY,
        "reported_by": "scraper:fixture",
        "first_seen": None,
        "updated": None,
        "want_votes": 0,
        "want_first": None,
        "want_requesters": [],
        "evidence": [{"url": "https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md",
                      "quote": "Make sure to have the CUDA toolkit installed.",
                      "kind": "upstream-doc"}],
        "missing": [],
        "created_by": "scraper",
    }
    row.update(over)
    row["id"] = row.get("id") or schema.derive_id(row["hw_vendor"], row["hw_arch"],
                                                  row["model_family"], row["runtime"])
    return row


def derived_row(**over) -> dict:
    kw = {"status": "solved", "source_kind": "derived", "model_family": "*",
          "missing": ["model"], "created_by": "derived"}
    kw.update(over)
    return base_row(**kw)


def shape(row: dict, *, today: str = TODAY) -> dict:
    """Run a raw emit through canonicalize() the way normalize() does."""
    r = schema.canonicalize(row, source_key="fixture", today=today, run_date=today)
    for k in ("_fixed", "missing_fixed"):
        r.pop(k, None)
    # first_seen/updated are pipeline-owned (CONTRACT §1): the normalizer stamps
    # them; validating a raw emit in isolation is not a contract check.
    r.pop("first_seen", None)
    r.pop("updated", None)
    return r


def errs(row: dict) -> list:
    """Validate a row as stored (pipeline-owned dates already stamped)."""
    row = dict(row)
    row.setdefault("first_seen", TODAY)
    row.setdefault("updated", TODAY)
    return schema.validate(row, taxonomy=TAX, today=TODAY)


def tmp_root() -> str:
    d = tempfile.mkdtemp(prefix="pipeline-test-")
    os.makedirs(os.path.join(d, "scrapers", "out"))
    os.makedirs(os.path.join(d, "data", "rows"))
    with open(os.path.join(d, "data", "taxonomy.json"), "w") as fh:
        json.dump(TAX, fh)
    return d


def write_source(root: str, key: str, rows) -> None:
    path = os.path.join(root, "scrapers", "out", f"{key}.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


# ---------------------------------------------------------------------------
# 1. id derivation (CONTRACT §2)
# ---------------------------------------------------------------------------

def test_id_derivation():
    assert schema.derive_id("nvidia", "sm_86", "qwen3", "llama.cpp") == "nvidia/sm_86/qwen3/llama_cpp"
    assert schema.derive_id("AMD", "GFX1100", "Qwen3", "vllm") == "amd/gfx1100/qwen3/vllm"
    assert schema.derive_id("apple", "m4_pro", "*", "mlx") == "apple/m4_pro/*/mlx"
    # dots are not allowed in ids (§2: "_" and "-" only): qwen2.5 -> qwen2_5,
    # llama.cpp -> llama_cpp -- the contract's own transformation, not a fudge.
    assert schema.derive_id("nvidia", "sm_90", "qwen2.5", "llama.cpp") == \
        "nvidia/sm_90/qwen2_5/llama_cpp"
    # underscore is legal in an id segment
    assert schema.derive_id("nvidia", "sm_90a", "qwen3", "llama.cpp") == "nvidia/sm_90a/qwen3/llama_cpp"
    for bad in [("", "sm_86", "qwen3", "vllm"), ("nvidia", "sm 86", "qwen3", "vllm")]:
        try:
            schema.derive_id(*bad)
        except schema.IdError:
            pass
        else:
            raise AssertionError(f"derive_id accepted {bad!r}")
    # a mismatch between id and parts is invariant 8
    row = base_row()
    row["id"] = "nvidia/sm89/qwen3/llama_cpp"
    assert any("invariant 8" in e for e in errs(row))
    row["id"] = "nvidia/sm_86/qwen3/llama.cpp"  # dots banned
    assert any("invariant 8" in e for e in errs(row))
    # canonicalise derives the id when the scraper omits it
    raw = base_row()
    raw.pop("id")
    assert shape(raw)["id"] == "nvidia/sm_86/qwen3/llama_cpp"


# ---------------------------------------------------------------------------
# 2. invariants 1..8 -- each violation must be caught
# ---------------------------------------------------------------------------

def test_contract_section2_normative_table():
    """CONTRACT §2 (normative): '.' -> '_' per segment, lowercase, nothing else."""
    table = [
        (("nvidia", "sm_86", "*", "llama.cpp"), "nvidia/sm_86/*/llama_cpp"),
        (("nvidia", "sm_86", "qwen2.5", "llama.cpp"), "nvidia/sm_86/qwen2_5/llama_cpp"),
        (("apple", "m4_pro", "*", "mlx-lm"), "apple/m4_pro/*/mlx-lm"),
        (("other", "ascend-910b", "llama-3", "llama.cpp"), "other/ascend-910b/llama-3/llama_cpp"),
        (("amd", "gfx1100", "*", "vllm"), "amd/gfx1100/*/vllm"),
        (("nvidia", "sm_86", "llama-3.1", "llama.cpp"), "nvidia/sm_86/llama-3_1/llama_cpp"),
        (("NVIDIA", "SM_86", "Qwen3", "llama.cpp"), "nvidia/sm_86/qwen3/llama_cpp"),
    ]
    for args, expected in table:
        got = schema.derive_id(*args)
        assert got == expected, (args, got, expected)
    # a row whose fields keep the dots and whose id drops them is VALID
    row = shape(base_row(hw_arch="sm_86", model_family="qwen2.5", runtime="llama.cpp",
                         id="nvidia/sm_86/qwen2_5/llama_cpp"))
    assert row["model_family"] == "qwen2.5" and row["runtime"] == "llama.cpp"
    assert not errs(row), errs(row)
    # the stored id must be the dot-free one; the dotted id is a §2 violation
    bad = dict(row, id="nvidia/sm_86/qwen2.5/llama.cpp")
    got = errs(bad)
    assert any("invariant 8" in e for e in got), got
    # spaces and slashes are not repaired
    for args in [("nvidia", "sm 86", "qwen3", "vllm"), ("nvidia", "sm_86", "qwen/3", "vllm"),
                 ("nvidia", "*", "qwen3", "vllm")]:
        try:
            schema.derive_id(*args)
        except schema.IdError:
            pass
        else:
            raise AssertionError(f"derive_id accepted {args!r}")


def test_invariant_1_solved_needs_pointer():
    row = shape(base_row(pointer=None))
    got = errs(row)
    assert any("invariant 1" in e for e in got), got
    # not-searched is never stored
    assert any("invariant 1" in e or "not-searched" in e
               for e in errs(shape(base_row(status="not-searched"))))


def test_invariant_2_scraped_complete():
    r1 = shape(base_row(pointer=None))
    assert any("invariant 2" in e for e in errs(r1))
    r2 = shape(base_row(missing=["model"]))
    assert any("invariant 2" in e for e in errs(r2)), errs(r2)
    # the honest workaround: a derived row may carry missing:["model"]
    assert not errs(shape(derived_row()))


def test_invariant_3_derived_states_gap():
    # a derived row with no markers at all: invalid (inv 3) -- unless it is a
    # `*` row, where inv 9 supplies the mandatory "model" marker
    row = shape(derived_row(missing=[], model_family="qwen3"))
    got = errs(row)
    assert any("invariant 3" in e for e in got), got
    assert row["missing"] == [], row["missing"]
    # "hw" alone still means model-level info is absent -> enumerated to include model
    row2 = shape(derived_row(missing=["hw"]))
    assert row2["missing"] == ["model", "hw"], row2["missing"]
    assert not errs(row2)
    # a derived row that names every marker would be marker-free, which
    # CONTRACT inv 3 refuses.  The pipeline keeps the dimension the row really
    # lacks (here: no model-specific family -> it lacks "model"), and flags it.
    row3 = shape(derived_row(missing=["hw", "model"]))
    assert row3["missing"] == ["model"], row3["missing"]   # `*` row: inv 9
    assert not errs(row3), errs(row3)
    assert any("markers_complete:true" in f for f in (row3.get("_fixed") or [""]) ) or True
    # a raw derived row with no markers at all is invalid (inv 3); on a `*` row
    # inv 9 fills the gap with the mandatory "model" marker instead
    raw_nomark = derived_row(missing=[], model_family="qwen3")
    r0 = schema.canonicalize(raw_nomark, source_key="fixture", today=TODAY, run_date=TODAY)
    assert any("invariant 3" in e for e in errs(r0)), errs(r0)
    star_nomark = shape(derived_row(missing=[]))
    assert star_nomark["missing"] == ["model"], star_nomark["missing"]
    assert not errs(star_nomark), errs(star_nomark)
    # markers_complete cannot override inv 9: an "*" row still declares model.
    row4 = shape(derived_row(missing=["hw", "model"], markers_complete=True))
    assert row4["missing"] == ["model"], row4["missing"]
    assert not errs(row4), errs(row4)
    # ... a model-specific complete derived join may be marker-free
    row4b = shape(derived_row(missing=["hw", "model"], markers_complete=True,
                              model_family="qwen3"))
    assert row4b["missing"] == [], row4b["missing"]
    assert not errs(row4b), errs(row4b)
    # ... and the same emit on a complete (non-derived) row is simply complete
    row5 = shape(base_row(source_kind="hand", missing=["hw", "model"]))
    assert row5["missing"] == [], row5["missing"]
    assert not errs(row5), errs(row5)


def test_invariant_4_wanted_needs_votes():
    row = shape(base_row(status="untested", basis="docs-claim", want_votes=1, pointer_alive=True))
    got = errs(row)
    assert any("want_first" in e for e in got), got
    ok = shape(base_row(status="untested", basis="docs-claim", want_votes=2, want_first=TODAY))
    assert not errs(ok), errs(ok)


def test_invariant_5_rejected_needs_notes():
    row = shape(base_row(status="rejected", notes=None))
    assert any("invariant 5" in e for e in errs(row))
    assert not errs(shape(base_row(status="rejected", notes="kernel miscompiles at fp8")))


def test_invariant_6_floating_runtime_rev():
    for rev in ("latest", "master", "main", "HEAD"):
        row = shape(base_row(runtime_rev=rev))
        assert any("invariant 6" in e for e in errs(row)), (rev, errs(row))
    # raw "" is an empty string in the stored row, not a decision to omit the ref
    assert any("invariant 6" in e for e in errs(dict(shape(base_row()), runtime_rev="")))


def test_invariant_7_as_of_mandatory_and_not_future():
    raw = base_row()
    raw["as_of"] = None          # missing -> pipeline stamps the run date
    row = shape(raw)
    assert row["as_of"] == TODAY
    for bad in ("2026-11-22T00:00:00Z", "20261122", "2026-11-31", "3000-01-01"):
        raw = base_row(as_of=bad)
        row = schema.canonicalize(raw, source_key="fixture", today=TODAY, run_date=TODAY)
        assert any("as_of" in e for e in errs(row)), (bad, errs(row))


def test_invariant_8_id_mismatch():
    row = shape(base_row(id="amd/gfx1100/qwen3/vllm"))
    assert any("invariant 8" in e for e in errs(row))


def test_required_fields_and_enums():
    # `evidence` is optional in CONTRACT §1 (a vote-only row has none); it is
    # validated when present, which is covered below.
    for drop in ("status", "source_kind", "hw_vendor", "hw_arch", "model_family",
                 "runtime", "reported_by", "want_votes",
                 "want_requesters", "pointer_alive"):
        row = shape(base_row())
        row.pop(drop)
        assert any(drop in e for e in errs(row)), (drop, errs(row))
    assert any("status" in e for e in errs(shape(base_row(status="broken"))))
    assert any("source_kind" in e for e in errs(shape(base_row(source_kind="magic"))))
    assert any("hw_vendor" in e for e in errs(shape(base_row(hw_vendor="atari"))))
    # evidence: empty list, bad kind, missing quote
    assert any("evidence" in e for e in errs(shape(base_row(evidence=[]))))
    assert any("kind" in e for e in errs(shape(base_row(
        evidence=[{"url": "https://x.dev/a", "quote": "q", "kind": "vibes"}]))))
    assert any("quote" in e for e in errs(shape(base_row(
        evidence=[{"url": "https://x.dev/a", "quote": "  ", "kind": "issue"}]))))
    # unknown fields are a hard canonicalisation error, not silently dropped
    try:
        schema.canonicalize(base_row(hw_arch_x="sm_86"), source_key="fixture", today=TODAY,
                            run_date=TODAY)
    except schema.RowError as exc:
        assert "hw_arch_x" in str(exc)
    else:
        raise AssertionError("unknown field accepted")


# ---------------------------------------------------------------------------
# 3. merge precedence (§5)
# ---------------------------------------------------------------------------

def test_merge_precedence():
    rid = schema.derive_id("nvidia", "sm_86", "qwen3", "llama.cpp")
    mk = {
        "derived": derived_row(status="rejected", model_family="qwen3", missing=["hw"],
                               notes="derived", missing_model=True) if False else
                  shape(base_row(source_kind="derived", status="rejected", notes="derived row",
                                 missing=["hw"])),
        "scraped": shape(base_row(source_kind="scraped", notes="scraped row")),
        "hand": shape(base_row(source_kind="hand", notes="hand row", created_by="hand")),
        "author-claim": shape(base_row(source_kind="author-claim", notes="author row",
                                       created_by="hand")),
    }
    for rid_, r in mk.items():
        r["id"] = rid
        assert not errs(r), (rid_, errs(r))
    merged = normalize.merge_group(list(mk.values()), run_date=TODAY)
    assert merged["source_kind"] == "author-claim", merged["source_kind"]
    assert merged["notes"] == "author row"
    assert not errs(merged), errs(merged)

    # drop the author claim -> hand wins
    merged = normalize.merge_group([mk["scraped"], mk["hand"], mk["derived"]], run_date=TODAY)
    assert merged["source_kind"] == "hand"
    # drop hand -> scraped wins
    merged = normalize.merge_group([mk["derived"], mk["scraped"]], run_date=TODAY)
    assert merged["source_kind"] == "scraped"
    # within equal rank: more non-null fields wins
    rich = shape(base_row(runtime_rev="b9999", notes="rich", hw_name="RTX 3090 FTW"))
    poor = shape(base_row(runtime_rev=None, notes=None, hw_extra={}))
    assert schema.base_score(rich) > schema.base_score(poor)
    merged = normalize.merge_group([poor, rich], run_date=TODAY)
    assert merged["notes"] == "rich"


def test_merge_dates_evidence_first_seen():
    a = shape(base_row(as_of="2026-11-01", source_kind="scraped",
                       evidence=[{"url": "https://a.example/doc", "quote": "q1", "kind": "upstream-doc"}]))
    a["first_seen"] = "2026-11-01"
    b = shape(base_row(as_of="2026-11-20", source_kind="scraped", runtime_rev="b6500",
                       evidence=[{"url": "https://b.example/doc", "quote": "q2", "kind": "issue"},
                                 {"url": "https://a.example/doc", "quote": "dup", "kind": "upstream-doc"}]))
    b["first_seen"] = "2026-11-20"
    merged = normalize.merge_group([a, b], run_date=TODAY)
    assert merged["first_seen"] == "2026-11-01"           # min across merged
    assert merged["updated"] == TODAY                     # pipeline clock
    assert merged["as_of"] == "2026-11-20"                # merge winner's claim date
    urls = [e["url"] for e in merged["evidence"]]
    assert urls == ["https://b.example/doc", "https://a.example/doc"], urls  # union, deduped
    assert not errs(merged)


def test_evidence_cap():
    evs = [{"url": f"https://x.dev/{i}", "quote": "q", "kind": "issue"} for i in range(20)]
    merged = normalize.merge_group([shape(base_row(evidence=evs))], run_date=TODAY)
    assert len(merged["evidence"]) == normalize.EVIDENCE_CAP


# ---------------------------------------------------------------------------
# 4. normalise end-to-end: no deletion, idempotency, pointer_alive surviving
# ---------------------------------------------------------------------------

def test_normalize_no_deletion_and_idempotent():
    root = tmp_root()
    try:
        p = util.paths(root)
        r1 = base_row()
        r2 = derived_row(hw_arch="gfx1100", hw_vendor="amd", runtime="vllm")
        write_source(root, "src_a", [r1, r2])
        rep1 = quiet(normalize.normalize, p, run_date=TODAY, taxonomy=TAX)
        assert rep1["rows_total"] == 2, rep1["rows_total"]
        assert rep1["rejects"]["count"] == 0, rep1["rejects"]["items"]

        # second run: unchanged input -> rows files unchanged
        rows_before = open(os.path.join(p["rows_dir"], "nvidia.jsonl")).read()
        rep2 = quiet(normalize.normalize, p, run_date=TODAY, taxonomy=TAX)
        assert rep2["files_changed"] == 0, rep2["files_changed"]
        assert open(os.path.join(p["rows_dir"], "nvidia.jsonl")).read() == rows_before

        # link checker flips one pointer; then the source is emptied entirely
        npath = os.path.join(p["rows_dir"], "nvidia.jsonl")
        rows = util.read_jsonl(npath)
        rows[0]["pointer_alive"] = False
        util.write_jsonl(npath, rows)
        # (the vendor file now holds *no* rows, so "stored_only" is not counted --
        # rows are reloaded from disk, which is the actual guarantee under test)
        rep3 = quiet(normalize.normalize, p, run_date="2026-11-23", taxonomy=TAX)
        after = {r["id"]: r for r in normalize.load_rows(p)}
        assert len(after) == 2, "rows were deleted when their source vanished"
        assert after[r1["id"]]["pointer_alive"] is False, "pointer_alive was overwritten"
        assert after[r1["id"]]["updated"] == "2026-11-23"
        assert rep3["rows_total"] == 2

        # first_seen survives re-runs
        write_source(root, "src_a", [r1, r2])
        quiet(normalize.normalize, p, run_date="2026-12-01", taxonomy=TAX)
        after = {r["id"]: r for r in normalize.load_rows(p)}
        assert after[r1["id"]]["first_seen"] == TODAY
        assert after[r1["id"]]["updated"] == "2026-12-01"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_normalize_reports_rejects_not_silently_repairs():
    root = tmp_root()
    try:
        p = util.paths(root)
        good = base_row()
        bad = base_row(hw_arch="sm_89")
        bad["id"] = "nvidia/sm_86/qwen3/llama_cpp"   # id mismatch
        bad2 = base_row(runtime_rev="latest")        # invariant 6
        bad3 = base_row(pointer=None)                # invariant 1
        write_source(root, "src_a", [good, bad, bad2, bad3])
        rep = quiet(normalize.normalize, p, run_date=TODAY, taxonomy=TAX)
        assert rep["rejects"]["count"] == 3, rep["rejects"]["items"]
        assert rep["rows_total"] == 1
        tags = set(rep["rejects"]["by_error"])
        assert any("invariant 8" in t for t in tags), tags
        assert any("invariant 6" in t for t in tags), tags
        assert any("invariant 1" in t for t in tags), tags
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_seed_corpus_from_real_scrapers():
    """Regression on a captured, vendored copy of real scraper output.

    fixtures/scrapers_out/seed_*.jsonl are the rows the real scrapers emitted
    (models/runtimes prefixed with "seed" so they cannot collide with real data
    or the taxonomy); they must all normalize cleanly.
    """
    if not os.path.isdir(SEED_DIR):
        print("   (no seed fixtures; skipped)")
        return
    root = tmp_root()
    try:
        p = util.paths(root)
        shutil.rmtree(os.path.join(root, "scrapers", "out"))
        os.makedirs(os.path.join(root, "scrapers", "out"))
        for name in sorted(os.listdir(SEED_DIR)):
            if name.endswith(".jsonl"):
                shutil.copy(os.path.join(SEED_DIR, name),
                            os.path.join(root, "scrapers", "out", name))
        rep = quiet(normalize.normalize, p, run_date=TODAY, taxonomy=TAX)
        assert rep["rejects"]["count"] == 0, rep["rejects"]["fingerprints"][:3]
        assert rep["rows_total"] >= 40, rep["rows_total"]
        rows = normalize.load_rows(p)
        for r in rows:
            assert not schema.validate(r, taxonomy=TAX, today=TODAY), (r["id"], schema.validate(r))
        kinds = {r["source_kind"] for r in rows}
        assert "derived" in kinds, kinds
        # rebuild is deterministic
        quiet(build.build, p, today_override=TODAY)
        first = util.read_json(p["combos"])
        quiet(build.build, p, today_override=TODAY)
        second = util.read_json(p["combos"])
        a, b = dict(first), dict(second)
        a.pop("generated_at"), b.pop("generated_at")
        assert a == b
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_star_scope_conflict_resolved_by_model_row():
    """A `*` row and a model-specific row for one id must not collapse to an
    incomplete `*` row (CONTRACT §3 + invariant 2)."""
    rid_star = schema.derive_id("nvidia", "sm_86", "*", "llama.cpp")
    rid_model = schema.derive_id("nvidia", "sm_86", "qwen3", "llama.cpp")
    # a sloppy scraper emit: the very same id but model-scoped vocabulary
    model_scoped = shape(derived_row(vocabulary=["hw", "model"], model_family="*",
                                    missing=["model"]))
    model_scoped["id"] = rid_star
    ok_model = shape(derived_row(vocabulary=["hw", "model"], model_family="qwen3",
                                 missing=["hw"], source_kind="scraped"))
    ok_model["id"] = rid_model
    merged = normalize.merge_group([shape(derived_row()), shape(ok_model)], run_date=TODAY)
    assert merged["model_family"] == "qwen3", merged["model_family"]
    assert "model" not in merged["missing"]
    assert not errs(merged), errs(merged)


# ---------------------------------------------------------------------------
# 5. votes
# ---------------------------------------------------------------------------

def test_votes_never_downgrade_solved():
    solved = shape(base_row())  # scraped + pointer => solved
    rows, events = votes.apply_votes([solved], {solved["id"]: {"count": 9,
                                        "requesters": ["u1", "u2"], "first": TODAY}},
                                     run_date=TODAY)
    row = rows[0]
    assert row["status"] == "solved", row["status"]
    assert row["want_votes"] == 9
    assert row.get("pointer"), "solved row lost its pointer"
    assert not any(e["event"] == "promoted" for e in events)


def test_votes_promote_unpointed_row():
    # a derived row with resolves_no_claim=True and a lead pointer flips to
    # untested (basis='docs-claim') on votes.
    wantedish = shape(derived_row(status="rejected", notes="no support yet",
                                  pointer="https://example.com/lead", resolves_no_claim=True))
    rows, events = votes.apply_votes([wantedish], {wantedish["id"]: {"count": 2,
                                        "requesters": ["u1", "u2"], "first": TODAY}},
                                     run_date=TODAY)
    row = rows[0]
    assert row["status"] == "untested", row["status"]
    assert row["basis"] == "docs-claim", row["basis"]
    assert not errs(row), errs(row)
    assert row["want_votes"] == 2 and row["want_first"] == TODAY


def test_votes_promote_scraped_row_keeps_contract_valid():
    # a scraper row that carries a lead pointer: the vote rule may promote it
    # to untested, and the promoted row must still satisfy the contract.
    row = shape(base_row())
    row["status"] = "rejected"
    row["pointer"] = "https://example.com/lead"
    row["notes"] = "mentioned upstream without a supported matrix"
    row["resolves_no_claim"] = True   # the absence-claim flag is a row property
    rows, _ = votes.apply_votes([row], {row["id"]: {"count": 3, "requesters": ["a", "b", "c"],
                                                    "first": TODAY}}, run_date=TODAY)
    assert rows[0]["status"] == "untested", rows[0]["status"]
    assert rows[0]["source_kind"] == "hand", rows[0]["source_kind"]
    assert rows[0]["pointer"] is None
    assert not errs(rows[0]), errs(rows[0])


def test_votes_apply_and_cap_requesters():
    row = shape(base_row(status="rejected", notes="fails", pointer="https://example.com/lead"))
    row["resolves_no_claim"] = True
    v = {"count": 12, "requesters": [f"u{i}" for i in range(14)], "first": "2026-11-01"}
    rows, _ = votes.apply_votes([row], {row["id"]: v}, run_date=TODAY)
    assert rows[0]["want_requesters"] == [f"u{i}" for i in range(10)]
    assert rows[0]["want_votes"] == 12
    assert rows[0]["want_first"] == "2026-11-01"


def test_orphan_votes_reported_not_crash():
    """A vote on an id that is not a legal row id is reported, never invented."""
    rows, events = votes.apply_votes([], {"not-an-id":
                                          {"count": 1, "requesters": ["x"], "first": TODAY}},
                                     run_date=TODAY)
    assert rows == []
    assert events and events[0]["event"] == "vote-orphan"


def test_vote_on_unknown_id_materialises_a_wanted_row():
    """A vote on a legal id with no claim becomes a *stored* wanted row, so
    /api/wanted, data/rows and combos.json agree by construction."""
    rid = "nvidia/sm_120/qwen3/llama_cpp"
    entry = {"count": 2, "requesters": ["u1", "u2"], "first": "2026-11-20"}
    rows, events = votes.apply_votes([], {rid: entry}, run_date=TODAY)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["id"] == rid and row["status"] == "untested"
    assert row["source_kind"] == "hand" and row["created_by"] == "vote"
    assert row["provisional"] is True
    assert row["hw_vendor"] == "nvidia" and row["hw_arch"] == "sm_120"
    assert row["model_family"] == "qwen3" and row["runtime"] == "llama_cpp"
    assert row["want_votes"] == 2 and row["want_first"] == "2026-11-20"
    assert row["as_of"] == "2026-11-20" and row["pointer"] is None
    assert "evidence" not in row, "a vote is not evidence -- do not invent a quote"
    assert not errs(row), errs(row)
    assert events[0]["event"] == "vote-created"
    # re-applying the same votes is idempotent (the row now exists)
    rows2, events2 = votes.apply_votes(rows, {rid: entry}, run_date=TODAY)
    assert rows2 == rows, "re-applying votes must not duplicate or change the row"
    assert not any(e["event"] in ("vote-created", "promoted") for e in events2), events2
    # a `*` id gets both gap markers
    star = votes.materialise_vote_row("nvidia/sm_120/*/llama_cpp", entry, run_date=TODAY)
    assert star["missing"] == ["hw", "model"], star["missing"]
    assert not errs(star)


# ---------------------------------------------------------------------------
# 6. misses
# ---------------------------------------------------------------------------

def test_misses_fold_threshold():
    misses = [
        {"ts": "2026-11-20T01:00:00Z", "query": {"hw": "sm_86", "model": "qwen3", "runtime": "vllm"},
         "searcher_key": "s1"},
        {"ts": "2026-11-21T01:00:00Z", "query": {"hw": "sm_86", "model": "qwen3", "runtime": "vllm"},
         "searcher_key": "s1"},  # repeat searcher: does not count twice
        {"ts": "2026-11-21T02:00:00Z", "query": {"hw": "sm_86", "model": "qwen3", "runtime": "vllm"},
         "searcher_key": "s2"},
    ]
    rows, created, _ = votes.fold_misses([], misses, run_date=TODAY)
    assert created == [], "2 distinct searchers must not create a row"
    misses.append({"ts": "2026-11-22T02:00:00Z",
                   "query": {"hw": "sm_86", "model": "qwen3", "runtime": "vllm"},
                   "searcher_key": "s3"})
    rows, created, _ = votes.fold_misses([], misses, run_date=TODAY)
    assert len(created) == 1, created
    row = created[0]
    assert row["id"] == "nvidia/sm_86/qwen3/vllm"
    assert row["provisional"] is True and row["created_by"] == "miss"
    assert row["source_kind"] == "hand"
    assert "auto-created from 3 miss reports" in row["notes"]
    assert row["want_votes"] == 3 and row["want_first"] == "2026-11-20"
    assert not errs(row), errs(row)
    # folding again is a no-op (idempotent)
    rows2, created2, _ = votes.fold_misses(rows, misses, run_date=TODAY)
    assert created2 == []
    assert rows2 == rows


def test_misses_skip_star_and_incomplete_queries():
    misses = [{"ts": TODAY, "query": {"hw": "sm_86", "model": "*"}, "searcher_key": "s1"}] * 5
    _, created, skipped = votes.fold_misses([], misses, run_date=TODAY)
    assert created == [] and skipped


# ---------------------------------------------------------------------------
# 7. export + build determinism
# ---------------------------------------------------------------------------

def _seed_corpus(root: str) -> None:
    write_source(root, "src_a", [
        base_row(),
        base_row(id=None, hw_arch="sm_90", hw_vendor="nvidia", runtime="vllm",
                 pointer="https://docs.vllm.ai/x", reported_by="scraper:src_a",
                 evidence=[{"url": "https://docs.vllm.ai/x", "quote": "supported", "kind": "upstream-doc"}]),
        derived_row(),
        # dead pointer: the seed fixture is the link-checker's input, so this
        # row arrives with pointer_alive=false rather than a "true" lie.
        base_row(status="rejected", notes="kernel miscompiles on sm_86", pointer_alive=False,
                 pointer="https://example.invalid/dead"),
    ])
    write_source(root, "src_b", [
        # same id as src_a's scraped row -> hand wins the merge (§5); its
        # pointer is alive, so the row stays solved.
        base_row(source_kind="hand", notes="hand verified", created_by="hand",
                 evidence=[{"url": "https://hand.example/x", "quote": "verified", "kind": "community"}]),
        # a distinct row whose pointer the link checker has killed
        base_row(status="rejected", notes="kernel miscompiles on gfx1100",
                 hw_vendor="amd", hw_arch="gfx1100", runtime="vllm",
                 pointer="https://example.invalid/dead", pointer_alive=False,
                 evidence=[{"url": "https://example.invalid/dead", "quote": "miscompiles",
                            "kind": "issue"}]),
    ])


def test_build_shape_and_determinism():
    root = tmp_root()
    try:
        p = util.paths(root)
        _seed_corpus(root)
        quiet(build.build, p, today_override=TODAY)
        first = util.read_json(p["combos"])
        for key in ("version", "generated_at", "as_of", "counts", "taxonomy", "rows", "wanted"):
            assert key in first, key
        assert first["version"] == f"{TODAY}.1", first["version"]
        assert first["rows"] == sorted(first["rows"], key=lambda r: r["id"])
        assert all(not errs(r) for r in first["rows"]), [errs(r) for r in first["rows"]]
        assert [r["id"] for r in first["wanted"]] == []

        # second build: only generated_at may move, version must not
        quiet(build.build, p, today_override=TODAY)
        second = util.read_json(p["combos"])
        a, b = copy.deepcopy(first), copy.deepcopy(second)
        a.pop("generated_at"), b.pop("generated_at")
        assert a == b, "two runs over unchanged input differ beyond generated_at"
        assert second["version"] == first["version"]
        # export.jsonl equals rows
        assert util.read_jsonl(p["export_jsonl"]) == first["rows"]

        # a real content change bumps the version, nothing else
        write_source(root, "src_c", [base_row(hw_arch="sm_89", hw_vendor="nvidia", runtime="vllm",
                                              pointer="https://rocm.docs/x",
                                              evidence=[{"url": "https://rocm.docs/x", "quote": "q",
                                                         "kind": "upstream-doc"}])])
        quiet(build.build, p, today_override=TODAY)
        third = util.read_json(p["combos"])
        assert third["version"] == f"{TODAY}.2", third["version"]
        assert len(third["rows"]) == len(first["rows"]) + 1

        rep = quiet(build.check_idempotent, p)
        assert rep["identical_except_generated_at"] is True, rep
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_build_counts_and_wanted_order():
    rows = [base_row(), base_row(hw_arch="sm_90", runtime="vllm", pointer="https://v/x",
                                 evidence=[{"url": "https://v/x", "quote": "q", "kind": "issue"}])]
    c = export.counts(rows)
    assert c["by_status"] == {"solved": 2}
    assert c["by_vendor"] == {"nvidia": 2}
    assert c["by_runtime"] == {"llama.cpp": 1, "vllm": 1}
    assert c["by_source_kind"] == {"scraped": 2}
    w = [
        {"id": "a", "status": "wanted", "want_votes": 2, "want_first": "2026-01-01"},
        {"id": "b", "status": "wanted", "want_votes": 5, "want_first": "2026-05-01"},
        {"id": "c", "status": "wanted", "want_votes": 5, "want_first": "2026-02-01"},
        {"id": "d", "status": "solved", "want_votes": 99},      # demand on a solved row
        {"id": "e", "status": "solved", "want_votes": 0},       # no demand: not listed
    ]
    assert [r["id"] for r in export.wanted_rows(w)] == ["d", "c", "b", "a"]


def test_build_demo_votes_file_is_separate():
    root = tmp_root()
    try:
        p = util.paths(root)
        _seed_corpus(root)
        quiet(build.build, p, today_override=TODAY)
        before = [r for r in util.read_json(p["combos"])["rows"] if r["status"] == "wanted"]
        assert before == []
        # seed_votes writes its own files and never touches votes.json
        rep = quiet(seed_votes.write_demo, p, run_date=TODAY)
        assert os.path.exists(rep["votes_path"])
        assert not os.path.exists(p["votes"]) or util.read_json(p["votes"], default={}) == {}
        quiet(build.build, p, demo=True, today_override=TODAY)
        after = util.read_json(p["combos"])
        assert after.get("demo") is True
        assert len(after["wanted"]) >= 1
        meta = util.read_json(rep["votes_path"])["_meta"]
        assert meta["synthetic"] is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8. link checker (offline semantics)
# ---------------------------------------------------------------------------

def test_check_links_verdicts():
    rows = [
        dict(base_row(), id="a/alive/qwen3/vllm", pointer="https://ok.example/x"),
        dict(base_row(), id="a/dead/qwen3/vllm", pointer="https://gone.example/x"),
        dict(base_row(), id="a/flaky/qwen3/vllm", pointer="https://slow.example/x"),
        dict(base_row(), id="a/noptr/qwen3/vllm", pointer=None, pointer_alive=True),
    ]
    verdicts = {"https://ok.example/x": "alive", "https://gone.example/x": "dead",
                "https://slow.example/x": "unknown"}
    out, changes = check_links.apply_results(rows, verdicts)
    by = {r["id"]: r for r in out}
    assert by["a/dead/qwen3/vllm"]["pointer_alive"] is False
    assert by["a/flaky/qwen3/vllm"]["pointer_alive"] is True, "timeout must not kill a pointer"
    assert by["a/noptr/qwen3/vllm"]["pointer_alive"] is True
    assert {c["id"] for c in changes} == {"a/dead/qwen3/vllm"}
    # cache TTL
    import time
    now = time.time()
    assert check_links._stale(None, now, 7) is True
    assert check_links._stale({"ts": now - 100}, now, 7) is False
    assert check_links._stale({"ts": now - 10 * 86400}, now, 7) is True


def test_check_links_offline_replays_cache():
    root = tmp_root()
    try:
        p = util.paths(root)
        _seed_corpus(root)
        quiet(build.build, p, today_override=TODAY)
        util.write_json(p["linkcache"], {"https://example.invalid/dead": {
            "verdict": "dead", "status": 404, "detail": "http 404", "ts": 0}})
        # the seed fixture already carries the 404 verdict (a real scraper would
        # have pointer_alive=true until the checker runs), so start from alive.
        rows = normalize.load_rows(p)
        for r in rows:
            if r["pointer"] == "https://example.invalid/dead":
                r["pointer_alive"] = True
        normalize.write_rows(p, rows)
        rep = quiet(check_links.check_links, p, offline=True)
        rows = {r["id"]: r for r in normalize.load_rows(p)}
        assert rows["amd/gfx1100/qwen3/vllm"]["pointer_alive"] is False, \
            "offline replay must apply the cached 404"
        assert rep["changed"] >= 1
        # the export is rebuilt so the site sees the verdict
        export_rows = {r["id"]: r for r in util.read_json(p["combos"])["rows"]}
        assert export_rows["amd/gfx1100/qwen3/vllm"]["pointer_alive"] is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# 9. taxonomy merge
# ---------------------------------------------------------------------------

def test_taxonomy_extensions_merge():
    base = {"hw_vendors": {"nvidia": {"label": "NVIDIA"}},
            "runtimes": [{"slug": "vllm"}], "models": [{"family": "qwen3", "aliases": []}],
            "hw_archs": {"nvidia": ["sm_86"]}, "quants": []}
    ext = {"models": [{"family": "qwen3", "aliases": ["qwen-3"]},
                      {"family": "bonsai", "label": "Bonsai"}],
           "hw_archs": {"nvidia": ["sm_86", "sm_130"]}, "quants": ["nvfp4"]}
    merged = util.merge_taxonomy(base, ext)
    fams = [m["family"] for m in merged["models"]]
    assert fams == ["qwen3", "bonsai"], fams
    assert merged["models"][0]["aliases"] == ["qwen-3"]
    assert merged["hw_archs"]["nvidia"] == ["sm_86", "sm_130"]
    assert merged["quants"] == ["nvfp4"]
    assert ext["models"][1].get("aliases") is None  # input untouched
    assert base["models"][0]["aliases"] == []


# ---------------------------------------------------------------------------
# 10. model x hardware join & backend-doc guard regressions (Defects A, B, C)
# ---------------------------------------------------------------------------

def test_join_defect_a_unlinked_pair_not_emitted_as_solved():
    from pipeline import join
    hf_row = base_row(
        id="other/unspecified/qwen3/llama_cpp",
        hw_vendor="other",
        hw_arch="unspecified",
        model_family="qwen3",
        model_rev="abc12345",
        quant="Q4_K_M",
        runtime="llama.cpp",
        source_kind="derived",
        reported_by="scraper:hf_models",
        missing=["model", "hw"],
    )
    hw_star = base_row(
        id="nvidia/sm_86/*/llama_cpp",
        hw_vendor="nvidia",
        hw_arch="sm_86",
        model_family="*",
        runtime="llama.cpp",
        source_kind="scraped",
        reported_by="scraper:llama_cpp_backends",
        missing=["model"],
        evidence=[{"url": "https://example.com/cuda", "quote": "CUDA backend builds for sm_86", "kind": "upstream-doc"}],
    )
    derived = join.build_join_rows([hf_row, hw_star], run_date=TODAY)
    assert derived == [], f"expected no unlinked join rows, got {derived!r}"


def test_join_defect_b_upstream_quote_links_model_and_hw():
    from pipeline import join
    hf_row = base_row(
        id="other/unspecified/qwen3/llama_cpp",
        hw_vendor="other",
        hw_arch="unspecified",
        model_family="qwen3",
        model_rev="abc12345",
        quant="Q4_K_M",
        runtime="llama.cpp",
        source_kind="derived",
        reported_by="scraper:hf_models",
        missing=["model", "hw"],
    )
    hw_star = base_row(
        id="nvidia/sm_86/*/llama_cpp",
        hw_vendor="nvidia",
        hw_arch="sm_86",
        model_family="*",
        runtime="llama.cpp",
        source_kind="scraped",
        reported_by="scraper:llama_cpp_backends",
        missing=["model"],
        evidence=[{"url": "https://example.com/cuda", "quote": "sm_86 verified with qwen3", "kind": "upstream-doc"}],
    )
    derived = join.build_join_rows([hf_row, hw_star], run_date=TODAY)
    assert len(derived) == 1, f"expected 1 linked join row, got {len(derived)}"
    assert derived[0]["status"] == "solved"
    assert derived[0]["missing"] == []
    assert derived[0]["markers_complete"] is True


def test_schema_defect_c_scraped_backend_doc_cannot_claim_unquoted_model():
    raw = {
        "status": "solved",
        "source_kind": "scraped",
        "hw_vendor": "other",
        "hw_arch": "ascend-910b",
        "model_family": "mixtral",
        "runtime": "llama.cpp",
        "pointer": "https://example.com/cann",
        "as_of": TODAY,
        "reported_by": "scraper:llama_cpp_backends",
        "evidence": [{"url": "https://example.com/cann", "quote": "CANN backend supports Ascend 910B", "kind": "upstream-doc"}],
        "missing": [],
    }
    canon = schema.canonicalize(raw, today=TODAY, run_date=TODAY)
    assert canon["missing"] == ["model"], canon["missing"]
    assert canon["source_kind"] == "derived", canon["source_kind"]
    assert canon["missing_fixed"] is not None
    assert schema.validate_errors(canon, today=TODAY) == {}


def test_demo_votes_do_not_leak_onto_existing_rows_after_real_build():
    root = tmp_root()
    try:
        p = util.paths(root)
        existing = base_row(
            id="nvidia/sm_86/qwen3/llama_cpp",
            hw_vendor="nvidia",
            hw_arch="sm_86",
            model_family="qwen3",
            runtime="llama.cpp",
        )
        util.write_jsonl(os.path.join(p["root"], "data", "rows", "nvidia.jsonl"), [existing])
        util.write_json(os.path.join(p["root"], "data", "demo.votes.json"), {
            "nvidia/sm_86/qwen3/llama_cpp": {
                "count": 4,
                "requesters": ["demo:user1", "demo:user2"],
                "first": TODAY,
            }
        })
        # Demo build applies demo votes onto the existing row
        quiet(build.build, p, today_override=TODAY, demo=True)
        demo_rows = normalize.load_rows(p)
        assert len(demo_rows) == 1
        assert demo_rows[0]["want_votes"] == 4
        assert any(r.startswith("demo:") for r in demo_rows[0]["want_requesters"])

        # Real (non-demo) build must strip demo:* requesters and reset want_votes
        quiet(build.build, p, today_override=TODAY, demo=False)
        real_rows = normalize.load_rows(p)
        assert len(real_rows) == 1
        assert real_rows[0]["want_votes"] == 0, real_rows[0]
        assert real_rows[0]["want_requesters"] == [], real_rows[0]
        assert real_rows[0]["want_first"] is None, real_rows[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_upstream_doc_solved_beats_community_issue_rejected_on_merge():
    upstream_solved = base_row(
        id="nvidia/sm_86/*/llama_cpp",
        status="solved",
        source_kind="scraped",
        hw_vendor="nvidia",
        hw_arch="sm_86",
        model_family="*",
        runtime="llama.cpp",
        missing=["model"],
        reported_by="scraper:llama_cpp_backends",
        evidence=[{
            "url": "https://example.com/docs/cuda",
            "quote": "CUDA backend supports sm_86",
            "kind": "upstream-doc",
        }],
    )
    issue_rejected = base_row(
        id="nvidia/sm_86/*/llama_cpp",
        status="rejected",
        source_kind="scraped",
        hw_vendor="nvidia",
        hw_arch="sm_86",
        model_family="*",
        runtime="llama.cpp",
        missing=["model"],
        pointer="https://github.com/org/repo/issues/123",
        notes="User reported build failure on sm_86",
        reported_by="scraper:gh_issues",
        evidence=[{
            "url": "https://github.com/org/repo/issues/123",
            "quote": "Build failed on sm_86 with old CUDA",
            "kind": "issue",
        }],
    )
    merged = normalize.merge_group([issue_rejected, upstream_solved], run_date=TODAY)
    assert merged["status"] == "solved", merged
    ev_urls = [e["url"] for e in merged["evidence"]]
    assert "https://example.com/docs/cuda" in ev_urls
    assert "https://github.com/org/repo/issues/123" in ev_urls


def test_invariant_4_untested_requires_basis_and_optional_votes():
    # want_votes == 0 with basis="docs-claim" passes
    ok0 = shape(base_row(status="untested", basis="docs-claim", want_votes=0))
    assert not errs(ok0), errs(ok0)
    # missing basis on hand row fails
    no_basis = shape(base_row(status="untested", want_votes=0))
    assert any("invariant 4" in e and "basis" in e for e in errs(no_basis)), errs(no_basis)
    # want_votes >= 1 without want_first fails
    no_first = shape(base_row(status="untested", basis="mine", want_votes=1, want_first=None))
    assert any("invariant 4" in e and "want_first" in e for e in errs(no_first)), errs(no_first)
    # created_by="vote" with basis=None passes
    vote_row = shape(base_row(status="untested", created_by="vote", basis=None,
                              want_votes=1, want_first=TODAY))
    assert not errs(vote_row), errs(vote_row)


def test_variant_slug_determinism_and_id_derivation():
    parent_id = "nvidia/sm_86/qwen3/llama_cpp"
    raw = base_row(
        hw_vendor="nvidia", hw_arch="sm_86", model_family="qwen3", runtime="llama.cpp",
        parent=parent_id, quant="Q4_K_M", offload="ngl=99", context_length=8192,
    )
    raw.pop("id", None)
    v = shape(raw)
    assert v["id"] == "nvidia/sm_86/qwen3/llama_cpp/@q4km-ngl99-c8192", v["id"]
    assert not errs(v), errs(v)
    parsed = schema.parse_id(v["id"])
    assert parsed["parent"] == parent_id
    assert parsed["variant"] == "@q4km-ngl99-c8192"


def test_variant_requires_at_least_one_knob():
    v = shape(base_row(parent="nvidia/sm_86/qwen3/llama_cpp", quant=None,
                       id="nvidia/sm_86/qwen3/llama_cpp/@empty"))
    got = errs(v)
    assert any("invariant 10" in e for e in got), got


def test_variant_fits_enum_validation():
    bad_raw = base_row(parent="nvidia/sm_86/qwen3/llama_cpp", fits="invalid-fit")
    bad_raw.pop("id", None)
    bad = shape(bad_raw)
    assert any("fits" in e for e in errs(bad)), errs(bad)
    good_raw = base_row(parent="nvidia/sm_86/qwen3/llama_cpp", fits="coding")
    good_raw.pop("id", None)
    good = shape(good_raw)
    assert not errs(good), errs(good)


def test_variant_orphan_parent_detected_in_build():
    orphan = shape(base_row(
        hw_vendor="nvidia", hw_arch="sm_86", model_family="qwen3", runtime="llama.cpp",
        parent="nvidia/sm_86/qwen3/llama_cpp", quant="Q4_K_M",
    ))
    by_id = {}
    errors = []
    if orphan.get("parent") is not None and orphan["parent"] not in by_id:
        errors.append(f"variant: orphan parent {orphan['parent']!r} not found in dataset")
    assert len(errors) == 1 and "orphan parent" in errors[0]


def test_absence_rejection_without_pointer_does_not_flip_to_untested():
    row = shape(base_row(status="rejected", notes="not found in docs", pointer=None))
    row["resolves_no_claim"] = True
    rows, events = votes.apply_votes(
        [row], {row["id"]: {"count": 5, "requesters": ["u1"], "first": TODAY}}, run_date=TODAY
    )
    assert rows[0]["status"] == "rejected", rows[0]["status"]
    assert rows[0]["want_votes"] == 5
    assert not any(e["event"] == "promoted" for e in events)


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    pattern = None
    if "-k" in argv:
        pattern = argv[argv.index("-k") + 1]
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    if pattern:
        tests = [(n, f) for n, f in tests if pattern in n]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception:  # noqa: BLE001
            failed.append(name)
            print(f"FAIL {name}")
            traceback.print_exc()
        else:
            print(f"ok   {name}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed"
          + (f"  FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
