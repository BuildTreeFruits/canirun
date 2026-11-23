# scrapers/ — seed corpus & upstream extractors

Each module in `scrapers/sources/` implements `SOURCE_KEY` + `fetch(http) -> (rows, rejects)`.
`scrapers/run_all.py` runs all registered sources, validates every emitted row against [CONTRACT.md](../CONTRACT.md) §1/§2, and writes:

| File | Description |
|---|---|
| `scrapers/out/<key>.jsonl` | Accepted rows, sorted by `(id, as_of)` — deterministic and idempotent |
| `scrapers/out/<key>.rejects.json` | Rows refused by the validator, with reasons |
| `scrapers/out/runtime_revs.json` | Pinned `runtime_rev` per runtime repo (release tag + URL + published date) |
| `scrapers/out/vllm_install.wheels.json` | vLLM ROCm wheel matrix (variant × Python × ROCm × glibc × versions) |
| `scrapers/runs.jsonl` | Audit log of each source run (`rows_in`, `rows_out`, `rejects`, HTTP status counts, duration) |
| `data/taxonomy.extensions.json` | Hardware architectures and model families discovered during scraping (merged by `pipeline/build.py`) |

## Usage

```bash
python3 scrapers/run_all.py              # Live fetch with 6h cache TTL, 1 req/s rate limit per host
python3 scrapers/run_all.py --fresh      # Re-fetch all sources (using ETag conditional GET)
python3 scrapers/run_all.py --offline    # Replay scrapers/cache/ only (zero network calls)
python3 scrapers/run_all.py --only llama_cpp_backends vllm_install
python3 scrapers/validate_raw.py         # Re-validate all files currently in scrapers/out/
```

Set `GITHUB_TOKEN` in the environment when running `gh_issues` or `gh_releases` online to avoid unauthenticated GitHub REST/Search API rate limits.

## Anti-fabrication rules (non-negotiable)

* **`common.verbatim(text, needle)`** — Every evidence quote extracted from an upstream document is verified against the fetched document body (whitespace-normalized) and **raises** if absent. If upstream documentation changes its wording, the scraper fails loudly rather than emitting a stale or paraphrased quote.
* **No invented tokens** — Hardware slugs (`hw_arch`), quantization tokens (`quant`), and revisions (`model_rev`, `runtime_rev`) come strictly from values printed by the upstream source (a documentation line, a table cell, an issue title, a real filename, or a repository SHA).
* **Pre-write contract validation** — `validate_raw.validate()` enforces [CONTRACT.md](../CONTRACT.md) invariants before writing `scrapers/out/<key>.jsonl`; any row failing validation is diverted to `scrapers/out/<key>.rejects.json`.
* **Graceful degradation on network errors** — If an upstream endpoint returns 403/5xx or is unreachable, the run records the error in `scrapers/runs.jsonl` and falls back to the on-disk cache; it never invents placeholder rows.

## Sources

| Source Key | Upstream Targets | Raw Rows | Output Shape |
|---|---|---:|---|
| `curated_combos` | Verified upstream docs & Hugging Face model cards (`ggml-org/llama.cpp`, `vllm-project/vllm`, `ml-explore/mlx-lm`, `ollama/ollama`, `Qwen/*`, `deepseek-ai/*`, `mlx-community/*`, `ggml-org/*`) | 92 | Complete `hand` rows (`missing: []`) covering mainstream NVIDIA (`sm_61`..`sm_121`), AMD (`gfx906`..`gfx1201`), Apple Silicon (`m1`..`m5-max`), and Intel (`arc-a750`, `arc-a770`, `arc-b580`, `data-center-max-1550`) hardware × model × runtime combinations, including verified architectural `rejected` cases (e.g. native FP8 on `sm_86`/`gfx1100`, CUDA-only vLLM wheels on Apple Silicon). |
| `llama_cpp_backends` | `ggml-org/llama.cpp` (`docs/build.md`, `docs/backend/{AOCL,BLIS,CANN,ET,OPENCL,OPENVINO,SYCL,VirtGPU,ZenDNN,zDNN}.md`, `docs/backend/snapdragon/README.md`, `docs/build-s390x.md`, `docs/android.md`) + `ollama/ollama` (`docs/gpu.mdx`) | 71 | `scraped` and `derived` hardware-level (`*`) rows across CUDA, ROCm/HIP, Apple Metal (`m1`..`m5-max`), Intel SYCL (`arc-a770`, `arc-a750`, `arc-a730m`, `arc-b580`, `data-center-max-1550`/`1100`, Meteor/Arrow/Lunar/Panther Lake iGPUs), Intel OpenVINO/NPU, Qualcomm Hexagon/Adreno, Huawei Ascend CANN, Moore Threads MUSA, Esperanto ET-SOC-1, AMD ZenDNN (`zen3`..`zen5`), IBM zDNN (`z15`..`z17`), VirtGPU, ARM KleidiAI, plus Ollama's official NVIDIA (`sm_52`..`sm_121`) and AMD ROCm (`gfx908`..`gfx1201`) support matrices. |
| `apple_integrations` | `vllm-project/vllm-metal`, `ml-explore/mlx`, `ml-explore/mlx-lm`, `ollama/ollama` (`docs/gpu.mdx`) | 60 | Apple Silicon (`m1` through `m5-max` + `m4-ultra`) coverage for `mlx`, `mlx-lm`, `vllm-metal`, and `ollama`, including `vllm-metal` M5 NAX tensor acceleration and model-specific rows (`qwen3`, `stable-diffusion`). |
| `vllm_install` | `vllm-project/vllm` (`docs/getting_started/installation/{gpu,gpu.cuda.inc,gpu.rocm.inc,gpu.apple.inc,gpu.xpu.inc,cpu,cpu.apple.inc,cpu.arm.inc,cpu.x86.inc,cpu.s390x.inc}.md`) | 34 | CUDA CC 7.5+ floor (`sm_75`..`sm_121` solved; pre-7.5 Pascal/Volta `sm_60`, `sm_61`, `sm_70` rejected), ROCm (`gfx90a`, `gfx942`, `gfx950`, `gfx1100`, `gfx1101`, `gfx1150`, `gfx1151`, `gfx1200`, `gfx1201`), Apple Silicon, Intel XPU, and CPU targets (AVX-512/AVX2, ARMv8+ NEON/BF16, s390x VXE, AMD Zen 4/5). |
| `hf_models` | `huggingface.co/api/models` (`gguf`, `mlx`, `mlx-lm`, `vllm`, `exllamav2` filters + sibling blob trees) | 32 | `model_family × quant × runtime` rows with `model_rev` pinned to the repository commit SHA and `quant` verified against real repository filenames (`missing: ["model", "hw"]`, joined downstream with hardware rows by `pipeline/join.py`). |
| `gh_issues` | `api.github.com/search/issues` across engine × hardware queries (`llama.cpp`, `vllm`, `ollama`, `mlx-lm`) | 2 | `scraped` rows emitted only when an issue/PR title contains an explicit hardware compatibility or incompatibility verdict. Ordinary bug reports do not mark hardware as `rejected`. |
| `gh_releases` | `api.github.com/repos/<org>/<repo>/releases` (`llama.cpp`, `vllm`, `ollama`, `mlx-lm`) | 1 | Produces `scrapers/out/runtime_revs.json` (pinning rolling `b####` tags for `llama.cpp` and semantic release tags for other runtimes) plus release-note hardware claims. |

After deduplication, authority-ranked merging (`pipeline/normalize.py`), and cross-source model × hardware joining (`pipeline/join.py`), the pipeline produces **317 canonical rows** in `data/rows/*.jsonl` (`308 solved`, `9 rejected`, `0 invalid`).

## Design Boundaries & Honest Omissions

* **No row beats a guessed row** — If an upstream table lists a commit hash without a clear support verdict, or if a community fine-tune on Hugging Face does not map cleanly to a canonical family in `data/taxonomy.json`, the scraper skips it rather than guessing.
* **Explicit `missing` tracking** — Scraped backend documentation that only certifies a GPU architecture without naming a model family is emitted with `model_family: "*"` and `missing: ["model"]`. When `pipeline/join.py` combines a hardware backend row with an `hf_models` model row, the resulting row is marked `source_kind: "derived"` so users and agents can always distinguish direct upstream claims from synthesized joins.
