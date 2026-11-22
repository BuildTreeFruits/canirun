#!/usr/bin/env python3
"""Generate api/tests/fixtures/ — a tiny, CONTRACT-valid dataset for offline API tests.

Rows are hand-written (not scraped) and deliberately synthetic: they exist to exercise
every CONTRACT §4 branch (solved / wanted / rejected, `*` context rows, derived rows
carrying missing:["model"], a dead pointer) without depending on the pipeline.

Run:  python3 api/tests/make_fixtures.py
"""

import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
AS_OF = "2026-11-20"
TODAY = "2026-11-22"

EV = lambda url, quote, kind="upstream-doc": {"url": url, "quote": quote, "kind": kind}


def row(**kw):
    base = {
        "id": None, "status": "solved", "source_kind": "scraped", "provisional": False,
        "hw_vendor": "nvidia", "hw_arch": "sm_86", "hw_name": "RTX 3090 / A6000 class",
        "hw_extra": {"vram_gb": 24}, "model_family": "qwen3", "model_rev": None,
        "quant": None, "runtime": "llama.cpp", "runtime_rev": "b6400",
        "pointer": None, "notes": None, "measurement": None, "pointer_alive": True,
        "as_of": AS_OF, "reported_by": "fixture:api_tests",
        "first_seen": "2026-11-01", "updated": AS_OF,
        "want_votes": 0, "want_first": None, "want_requesters": [],
        "evidence": [], "missing": [], "created_by": "hand",
    }
    base.update(kw)
    # CONTRACT §2: dots are NOT allowed in id segments -- the id segment is the
    # flattened form of the runtime slug (llama.cpp -> llama_cpp), per
    # pipeline/schema.py runtime_id_segment().
    runtime_seg = str(base["runtime"]).replace(".", "_")
    model_seg = str(base["model_family"]).replace(".", "_") if base["model_family"] != "*" else "*"
    hw_seg = str(base["hw_arch"]).replace(".", "_")
    base["id"] = f'{base["hw_vendor"]}/{hw_seg}/{model_seg}/{runtime_seg}'
    return base


ROWS = [
    # --- a real solved answer ---------------------------------------------
    row(status="solved", source_kind="scraped", model_family="qwen3", runtime="llama.cpp",
        hw_arch="sm_86", quant="Q4_K_M", runtime_rev="b6400",
        pointer="https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cuda",
        notes="llama.cpp CUDA backend builds for sm_86 via -DGGML_CUDA=ON.",
        evidence=[EV("https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md",
                     "Make sure to have the CUDA toolkit installed.")]),
    # --- solved, AMD ------------------------------------------------------
    row(status="solved", source_kind="scraped", hw_vendor="amd", hw_arch="gfx1100",
        hw_name="RX 7900 XTX class", model_family="qwen3", runtime="vllm", runtime_rev="v0.11.0",
        pointer="https://github.com/vllm-project/vllm/blob/main/docs/getting_started/installation/gpu.md",
        evidence=[EV("https://github.com/vllm-project/vllm/blob/main/docs/getting_started/installation/gpu.md",
                     "vLLM supports AMD ROCm gfx1100.", "upstream-doc")]),
    # --- derived join: states what it lacks -------------------------------
    row(status="solved", source_kind="derived", hw_vendor="apple", hw_arch="m4_pro",
        hw_name="M4 Pro", model_family="qwen3", runtime="mlx-lm", runtime_rev="0.28.1",
        quant="mlx-4bit",
        pointer="https://huggingface.co/mlx-community/Qwen3-8B-4bit",
        missing=["hw"], evidence=[EV("https://huggingface.co/mlx-community/Qwen3-8B-4bit",
                                     "safetensors 4-bit", "model-repo")]),
    # --- a `*` hardware row with NO model (CONTRACT §3) -------------------
    # NOTE: derived, not scraped -- CONTRACT §3 wants missing:["model"] on a `*` row,
    # while §1 invariant 2 forbids missing != [] on scraped rows. Flagged to lead;
    # `derived` is the combination both rules accept.
    row(status="solved", source_kind="derived", hw_arch="sm_86", model_family="*",
        runtime="llama.cpp", runtime_rev="b6400", missing=["model"],
        pointer="https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cuda",
        notes="CUDA backend supports sm_86; model-independent backend claim.",
        evidence=[EV("https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md",
                     "CUDA is supported on compute capability 8.6.")]),
    # --- a `*` row for a vendor with NOTHING model-specific ---------------
    row(status="solved", source_kind="derived", hw_vendor="intel", hw_arch="arc-b580",
        hw_name="Arc B580", model_family="*", runtime="llama.cpp", runtime_rev="b6400",
        missing=["model"],
        pointer="https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md",
        evidence=[EV("https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/SYCL.md",
                     "Intel Arc B580", "upstream-doc")]),
    # --- wanted row -------------------------------------------------------
    row(status="wanted", source_kind="hand", hw_vendor="nvidia", hw_arch="sm_120",
        hw_name="RTX 5090", model_family="deepseek-v4", runtime="llama.cpp", runtime_rev=None,
        want_votes=3, want_first="2026-10-01", want_requesters=["gh:alice", "gh:bob", "gh:carol"],
        missing=["hw"], notes=None,
        evidence=[EV("https://github.com/ggml-org/llama.cpp/issues/1", "anyone got sm_120 working?",
                     "issue")]),
    # --- rejected row (notes mandatory) -----------------------------------
    row(status="rejected", source_kind="hand", hw_vendor="nvidia", hw_arch="sm_75",
        hw_name="T4", model_family="gemma-4", runtime="llama.cpp", runtime_rev="b6400",
        notes="gemma-4 needs bf16 matmul; T4 (sm_75) has no native bf16 path.",
        evidence=[EV("https://github.com/ggml-org/llama.cpp/issues/2", "illegal memory access on T4",
                     "issue")]),
    # --- dead pointer -----------------------------------------------------
    row(status="solved", source_kind="scraped", hw_vendor="amd", hw_arch="gfx90a",
        hw_name="MI210 / MI250 class", model_family="llama-3", runtime="llama.cpp",
        runtime_rev="b6400", pointer_alive=False,
        pointer="https://example.invalid/moved",
        evidence=[EV("https://example.invalid/moved", "old path", "upstream-doc")]),
]


def main():
    if os.path.isdir(FIX):
        shutil.rmtree(FIX)
    os.makedirs(os.path.join(FIX, "rows"), exist_ok=True)

    by_vendor = {}
    for r in ROWS:
        by_vendor.setdefault(r["hw_vendor"], []).append(r)
    for vendor, rows in by_vendor.items():
        rows.sort(key=lambda r: r["id"])
        with open(os.path.join(FIX, "rows", f"{vendor}.jsonl"), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    root = os.path.abspath(os.path.join(HERE, "..", ".."))
    with open(os.path.join(root, "data", "taxonomy.json"), encoding="utf-8") as fh:
        taxonomy = json.load(fh)
    with open(os.path.join(FIX, "taxonomy.json"), "w", encoding="utf-8") as fh:
        json.dump(taxonomy, fh, ensure_ascii=False, indent=1)

    counts = {}
    for r in ROWS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    combos = {
        "version": f"{AS_OF}.1",
        "generated_at": "2026-11-20T00:00:00Z",
        "as_of": AS_OF,
        "counts": {"by_status": counts},
        "taxonomy": taxonomy,
        "rows": sorted(ROWS, key=lambda r: r["id"]),
        "wanted": [r for r in ROWS if r["status"] == "wanted"],
    }
    with open(os.path.join(FIX, "combos.json"), "w", encoding="utf-8") as fh:
        json.dump(combos, fh, ensure_ascii=True, indent=1, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(FIX, "export.jsonl"), "w", encoding="utf-8") as fh:
        for r in sorted(ROWS, key=lambda r: r["id"]):
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    with open(os.path.join(FIX, "votes.json"), "w", encoding="utf-8") as fh:
        json.dump({}, fh)
    open(os.path.join(FIX, "misses.jsonl"), "w").close()
    print(f"wrote {len(ROWS)} fixture rows -> {FIX}")


if __name__ == "__main__":
    main()
