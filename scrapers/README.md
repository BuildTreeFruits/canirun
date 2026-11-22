# scrapers/ — seed corpus for the combo index

Each module in `scrapers/sources/` implements `SOURCE_KEY` + `fetch(http) -> (rows, rejects)`.
`scrapers/run_all.py` runs them all, validates every row against CONTRACT §1/§2, and writes:

| file | what |
|---|---|
| `scrapers/out/<key>.jsonl` | accepted rows, sorted by `(id, as_of)` — deterministic, idempotent |
| `scrapers/out/<key>.rejects.json` | rows refused by the validator, with reasons |
| `scrapers/out/runtime_revs.json` | pinned `runtime_rev` per repo (release tag + url + published_at) |
| `scrapers/out/vllm_install.wheels.json` | vLLM ROCm wheel matrix (variant × python × ROCm × glibc × versions) |
| `scrapers/runs.jsonl` | one line per source run: rows_in/out/rejects, http status counts, errors, duration |
| `data/taxonomy.extensions.json` | model families learned from HF repos (merged by the pipeline) |

```bash
python3 scrapers/run_all.py              # live, 6h cache TTL, 1 req/s per host
python3 scrapers/run_all.py --fresh      # re-fetch everything (ETag conditional GET)
python3 scrapers/run_all.py --offline    # replay scrapers/cache only, no network
python3 scrapers/run_all.py --only hf_models gh_issues
python3 scrapers/validate_raw.py         # re-validate whatever is in out/
```

## Anti-fabrication rules (non-negotiable)

* `common.verbatim(text, needle)` — every quote taken from a fetched document is re-checked
  against the fetched body (whitespace-normalised) and **raises** if absent. A doc upstream
  changing its wording fails the run loudly instead of emitting a stale quote.
* values like `hw_arch`, `quant`, `model_rev` come only from data the source printed
  (a doc line, an issue title, a real file name or repo sha) — never from a model name.
* `validate_raw.validate()` enforces CONTRACT §1 invariants 1–9 + §2 ids before anything is
  written; refused rows go to `<key>.rejects.json` and are printed by `run_all.py`.
* If a source cannot be reached (403 / offline / 5xx) the run **records** it in
  `runs.jsonl` and falls back to the on-disk cache; it never invents rows to fill a gap.

## Sources

| key | upstream | rows | shape |
|---|---|---|---|
| `llama_cpp_backends` | raw.githubusercontent.com `ggml-org/llama.cpp/master/docs/build.md`, `docs/backend/{AOCL,BLIS,CANN,ET,OPENCL,OPENVINO,SYCL,VirtGPU,ZenDNN,zDNN}.md`, `docs/backend/snapdragon/README.md`, `docs/build-s390x.md`, `docs/android.md` | 52 | `scraped` `*` rows where the doc names an arch/device it supports (CUDA CC 8.6/8.9, HIP gfx1030/gfx1100/gfx1031/gfx1035, MUSA MTT, SYCL verified-device table + release matrix, Adreno/Hexagon, Ascend, ZenDNN Zen3/4/5, zDNN z17, OpenVINO Lunar/Panther/NPU, ET-SOC, VirtGPU, KleidiAI); `derived` for build-flag/benchmark claims; `rejected` for SYCL's dropped NVIDIA support and zDNN's unsupported z16; 6 `scraped` model rows from CANN's model table and ET's supported-model list |
| `vllm_install` | raw.githubusercontent.com `vllm-project/vllm/main/docs/getting_started/installation/{gpu,gpu.cuda.inc,gpu.rocm.inc,gpu.apple.inc,gpu.xpu.inc,cpu,cpu.apple.inc,cpu.arm.inc,cpu.x86.inc,cpu.s390x.inc}.md` | 24 | CUDA CC 7.5 floor + named cards (T4/A100/L4/H100/B200), ROCm gfx90a/gfx942/gfx950/gfx1100/gfx1101/gfx1200/gfx1201/gfx1151/gfx1150 with per-card ROCm minimums, Apple Silicon via vLLM-Metal, Intel DC GPU/Arc XPU, CPU corners (AVX-512/AVX2, NEON, ARMv8.6 BF16, s390x VXE/z15, Zen 4/5 zentorch) |
| `hf_models` | huggingface.co `/api/models?filter={gguf,mlx,mlx-lm,vllm,exllamav2}` + `/api/models/<id>?blobs=true` | 32 | `model_family × quant`, `model_rev` = repo sha, pointer = repo page, `missing:["hw"]`; quant token must appear in a real sibling filename |
| `gh_issues` | api.github.com/search/issues over 34 engine×hardware queries (llama.cpp / vLLM / ollama / mlx-lm) | 13 | `scraped` `*` rows, evidence = issue/PR title (+body sentence), status from a verdict word **in the title** |
| `gh_releases` | api.github.com `/releases` for llama.cpp, vLLM, ollama, mlx-lm | 1 | main product is `out/runtime_revs.json`; a row only when a release bullet names an arch with a verdict |

## Known gaps (honest list)

**Current yield (2026-11-22 run, 122 rows total, 0 rejects; re-running `--offline` from the
cache reproduces the same 122 rows exactly):**

| source | rows | scraped | derived | rejected |
|---|---|---|---|---|
| llama_cpp_backends | 52 | 42 | 10 (8 solved + 2 rejected) | 2 |
| vllm_install | 24 | 24 | 0 | 0 |
| hf_models | 32 | 0 | 32 (missing `hw`) | 0 |
| gh_issues | 13 | 13 (12 rejected, 1 solved) | 0 | 12 |
| gh_releases | 1 | 1 | 0 | 1 |

* **Thin by design / abandoned:**
  * `gh_releases` — release notes rarely carry hardware claims; llama.cpp ships rolling
    `b####` builds via nightly-tag.txt so `releases/latest` is `v1.0.0`, and everything
    else named hw upstream (sycl/hip) is already covered by docs. Its real value is the
    side-file, not rows.
  * `gh_issues` — GitHub search is unauthenticated (60 req/h REST, ~10 search/min): the run
    regularly takes a 403 on ~1–2 of 34 queries and records it. Matched titles skew to
    `rejected` (people file issues when things break); `solved` issue rows are rare.
  * `hf_models` — only ~1 in 4 trending GGUF/MLX repos maps to a `data/taxonomy.json`
    family (the rest are fine-tunes/community finetunes whose family token we refuse to
    invent), so the budget (150 detail calls/run) buys ~30 families. Only the top repo per
    family is read, so per-family quant coverage is a sample, not exhaustive.
* **Deliberate omissions (no row beats a guessed row):**
  * SYCL hardware with only a release-matrix commit (no verified-device row) — not emitted.
  * CUDA compute caps other than 8.6/8.9: `build.md` names only those two; 7.5 (`sm_75`) is
    `derived` from the "build for any CC list" text.
  * `ml-explore/mlx` (the core library) is not scraped — `mlx-lm`'s README says only
    "Apple silicon"; no per-chip claims exist there to quote. Apple rows come from vLLM
    (Apple Silicon) and llama.cpp (Metal default) only.
  * ollama's own docs: `docs/gpu.md` 404s; no hardware table is scrapable upstream, so
    ollama rows exist only via `gh_issues`/`gh_releases`.
* **`examples/llama.android` / mobile** — `docs/android.md` only documents the build, so one
  `arm-cpu/arm64-android` row is `derived`, not a claim.

## Contract friction found while building this

1. **§2 vs the taxonomy**: `runtimes[].slug` contains dots (`llama.cpp`), and §2's id rule
   originally banned dots in id segments. Resolved by lead (2026-11-22): `.` → `_` in id
   segments only; `runtime`/`model_family` fields keep the dotted taxonomy value.
2. **§1 inv 2 vs §3**: the original "scraped ⇒ missing == []" made every honest hardware
   claim (`*` + `missing:["model"]`) invalid, forcing doc-backed claims to masquerade as
   `derived`. Resolved by lead: scraped may carry `missing:["model"]` when
   `model_family == "*"`, and inv 9 now requires that on every `*` row.
3. **§1 inv 3 vs the example**: the example row is `derived` with `missing:["model"]` (hw is
   known, model is not), which contradicts "derived states what it lacks" if read as
   "derived ⇒ missing hw". Our validator accepts `["model"]` and `["hw"]` for derived and
   requires at least one of them; hw_extra/x is on this side of the contract.
4. **`hw_arch` for CPU/other targets** has no taxonomy slots for several real values the docs
   name (`x86-64-amd-zen3/4/5`, `mtt-s4000`, `ascend-910b`, `ascend-310p`, `et-soc-1`,
   `ibm-z17`, `qualcomm hexagon-npu`, `arc-igpu-panther-lake`, `intel-npu`, ...). We emitted
   them as-is; `data/taxonomy.extensions.json` records what we learned on the model side.
5. **`first_seen`/`updated`** are required-adjacent in §1 but §1 says the pipeline sets them,
   so scrapers do not emit them (the pipeline's job to default).
6. `missing:["hw"]` for `hf_models` rows is upgraded by the pipeline to `["model","hw"]` —
   accepted (a model×quant row with no hardware join is indeed incomplete on both).
