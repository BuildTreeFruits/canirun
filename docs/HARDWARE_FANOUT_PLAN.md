# Master Hardware Expansion & Apple Completeness Fan-Out Plan (`solve.run`)

> **Purpose:** Single authoritative execution spec for fanning out parallel Hydrogen agents (via `/goal`, `/teamwork`, or `run_workflow`) to eliminate the hardware coverage gaps identified in [docs/MISSING_HARDWARE_ANALYSIS.md](file:///Users/windows/Model%20support%20for%20hardware%20site/docs/MISSING_HARDWARE_ANALYSIS.md).
>
> **Execution Model:** **2 Waves.**
> - **Wave 1 (5 parallel Hydrogen agents):** Strictly disjoint file write scopes. Zero shared mutable files; zero merge conflicts.
> - **Wave 2 (1 Integrator agent):** Runs after all 5 Wave 1 agents finish—registers any new scraper source, runs `scrapers/run_all.py --offline`, runs `pipeline/build.py --check`, regenerates `web/snapshot.js`, and runs the full test + coverage verification gate.

---

## 0. Non-Negotiable Invariants for All Agents

1. **Read `CONTRACT.md` first:** Do not change any field name, status enum (`solved | untested | rejected`), `source_kind` enum (`scraped | derived | hand | author-claim`), or canonical ID rule (`{hw_vendor}/{hw_arch}/{model_family}/{runtime}` lowercased with `.` → `_`, hyphens and underscores preserved).
2. **Strict Anti-Fabrication (`common.verbatim()`):**
   - Every scraper or curated row MUST verify its `evidence[].quote` against the fetched document body using `scrapers.common.verbatim(body, quote)`.
   - **Offline-first cache rule:** To guarantee deterministic, 100% offline-reproducible runs (`python3 scrapers/run_all.py --offline`), every URL used by a scraper in Wave 1 MUST either already exist in `scrapers/cache/` (or be copied into that scraper's `scrapers/cache/<source_key>/` directory from an existing cached file in `scrapers/cache/`). Never invent a URL or paraphrase a quote.
3. **Zero-Build Frontend (`file://` compatible):**
   - `web/js/*.js` files MUST remain classic IIFE scripts (`(function (SR) { ... })(window.__SR = window.__SR || {});`). Never use ES module `import` / `export` in `web/js/*.js`.
4. **Disjoint Write Scopes:**
   - No Wave 1 agent may write to any file outside its **Allowed Write Scope** in §1.
   - No Wave 1 agent may edit `scrapers/out/*.jsonl`, `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl`, or `web/snapshot.js` (those are generated exclusively by Wave 2).

---

## 1. Fan-Out Ownership Matrix (Disjoint Write Scopes)

### Wave 1 — 5 Parallel Hydrogen Agents

| Agent ID | Role | Allowed Write Scope (Exclusive) | Read-Only References |
|---|---|---|---|
| **H1-TAX** | `taxonomy-and-aliases` | `data/taxonomy.json`, `data/taxonomy.extensions.json` | `CONTRACT.md`, `docs/MISSING_HARDWARE_ANALYSIS.md`, `data/rows/*.jsonl` |
| **H1-APPLE** | `apple-silicon-expansion` | `scrapers/sources/apple_integrations.py`, `scrapers/cache/apple_integrations/**` | `CONTRACT.md`, `data/taxonomy.json`, `scrapers/common.py`, `scrapers/cache/curated_combos/**` |
| **H1-BACKENDS** | `ollama-and-sycl-scrapers` | `scrapers/sources/llama_cpp_backends.py`, `scrapers/sources/vllm_install.py`, `scrapers/cache/llama_cpp_backends/**` | `CONTRACT.md`, `data/taxonomy.json`, `scrapers/common.py`, `scrapers/cache/curated_combos/**` |
| **H1-CURATED** | `curated-model-hw-matrix` | `scrapers/sources/curated_combos.py` | `CONTRACT.md`, `data/taxonomy.json`, `scrapers/common.py`, `scrapers/cache/curated_combos/**` |
| **H1-CONTRIB** | `user-hw-submission-flow` | `web/js/app.js`, `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/submit-combo.yml`, `scripts/ingest_combo.py` *(new)* | `CONTRACT.md`, `data/taxonomy.json`, `pipeline/schema.py` |

### Wave 2 — 1 Integrator Agent (Runs ONLY After All 5 Wave 1 Agents Complete)

| Agent ID | Role | Allowed Write Scope |
|---|---|---|
| **H2-INT** | `hardware-integrator-verify` | `scrapers/out/**`, `scrapers/runs.jsonl`, `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl`, `web/snapshot.js`, `pipeline/tests/test_pipeline.py`, `api/tests/test_api.py`, `web/tests/smoke.mjs` |

---

## 2. Detailed Wave 1 Agent Specifications

---

### Agent H1-TAX: `taxonomy-and-aliases`

**Write Scope:** `data/taxonomy.json`, `data/taxonomy.extensions.json`

#### Tasks

1. **Sync All 26 Orphan Row Architectures into `data/taxonomy.json` (`hw_archs`):**
   Every architecture currently emitted by scrapers into `data/rows/*.jsonl` must be present in `data/taxonomy.json` `hw_archs` so it appears in UI dropdowns and vendor lookups:
   - **`amd`**: add `"gfx1035"` (RDNA2 Ryzen APU / Radeon 680M) and `"gfx1152"` (Krackan Point / Ryzen AI 300), `"gfx1103"` (Ryzen Z1 Extreme / 780M APU).
   - **`apple`**: add `"m4-ultra"`, `"m5-ultra"`, `"a17-pro"`, `"a18-pro"`, `"a19-pro"`.
   - **`arm-cpu`**:
     - Add `"aarch64-bf16"`, `"aarch64-sve2"`, `"aarch64-sme"`, `"grace-cpu"`.
     - Fix the chimeric typo slug `"rv64-spacemit-s390x"` → replace with `"rv64-spacemit"` (s390x is already covered under `other` as `ibm-z-s390x`).
   - **`intel`**: add `"arc-igpu-panther-lake"`, `"intel-igpu-11th-gen"`, `"intel-igpu-12th-gen"`, `"intel-npu"`, `"arc-pro-b60"`, `"gaudi-2"`, `"gaudi-3"`.
   - **`nvidia`**: add `"sm_52"` (Maxwell M40/Titan X / GTX 900), `"sm_110"` (Jetson AGX Thor).
   - **`qualcomm`**: add `"snapdragon-8-elite-gen5"`, `"snapdragon-7s-gen3"`, `"snapdragon-x2-elite"`, `"adreno-gpu"`.
   - **`x86-cpu`**: add `"x86-64-amd-zen2"`, `"x86-64-amd-zen3"`, `"x86-64-amd-zen4"`, `"x86-64-amd-zen5"`, `"generic"`.
   - **`other`**: add `"ascend-310p"`, `"ascend-910b"`, `"et-soc-1"`, `"ibm-z-s390x"`, `"ibm-z15"`, `"ibm-z16"`, `"ibm-z17"`, `"mtt-s80"`, `"mtt-s4000"`, `"mtt-s5000"`, `"virtgpu-generic"`, `"tpu-v5e"`, `"tpu-v6e"`, `"tenstorrent-wormhole"`.

2. **Expand `hw_aliases` in `data/taxonomy.json` Across All Major Vendors:**
   Add comprehensive retail-name, chip-name, and underscore-variant aliases to `data/taxonomy.json` `hw_aliases`:
   - **Apple Silicon aliases:**
     - Underscore variants: `"m1_pro": "m1-pro"`, `"m1_max": "m1-max"`, `"m1_ultra": "m1-ultra"`, `"m2_pro": "m2-pro"`, `"m2_max": "m2-max"`, `"m2_ultra": "m2-ultra"`, `"m3_pro": "m3-pro"`, `"m3_max": "m3-max"`, `"m3_ultra": "m3-ultra"`, `"m4_pro": "m4-pro"`, `"m4_max": "m4-max"`, `"m4_ultra": "m4-ultra"`, `"m5_pro": "m5-pro"`, `"m5_max": "m5-max"`, `"m5_ultra": "m5-ultra"`, `"a17_pro": "a17-pro"`, `"a18_pro": "a18-pro"`, `"a19_pro": "a19-pro"`.
     - Platform/device terms: `"apple-silicon": "m1"`, `"apple silicon": "m1"`, `"metal": "m1"`, `"mac-studio": "m4-max"`, `"mac-mini-m4": "m4"`, `"macbook-pro": "m4-pro"`, `"macbook-air": "m4"`.
   - **NVIDIA retail card & architecture aliases:**
     - `"dgx-spark": "sm_121"`, `"gb10": "sm_121"`, `"project-digits": "sm_121"`
     - `"rtx5080": "sm_120"`, `"rtx5070ti": "sm_120"`, `"rtx5070": "sm_120"`, `"rtx5060ti": "sm_120"`, `"rtx5060": "sm_120"`, `"rtx-pro-6000": "sm_120"`
     - `"gb200": "sm_100"`, `"b100": "sm_100"`, `"b300": "sm_103"`
     - `"h200": "sm_90"`, `"gh200": "sm_90"`
     - `"rtx4080": "sm_89"`, `"rtx4080super": "sm_89"`, `"rtx4070ti": "sm_89"`, `"rtx4070": "sm_89"`, `"rtx4060ti": "sm_89"`, `"rtx4060": "sm_89"`, `"l40s": "sm_89"`, `"l40": "sm_89"`, `"rtx6000ada": "sm_89"`
     - `"jetson-orin": "sm_87"`, `"agx-orin": "sm_87"`, `"orin-nano": "sm_87"`, `"jetson-thor": "sm_110"`
     - `"rtx3090ti": "sm_86"`, `"rtx3080ti": "sm_86"`, `"rtx3070": "sm_86"`, `"rtx3060": "sm_86"`, `"a6000": "sm_86"`, `"rtxa6000": "sm_86"`, `"a40": "sm_86"`, `"a10": "sm_86"`, `"a10g": "sm_86"`
     - `"a30": "sm_80"`
     - `"rtx2080ti": "sm_75"`, `"rtx2080": "sm_75"`, `"titanrtx": "sm_75"`, `"turing": "sm_75"`
     - `"v100": "sm_70"`, `"titanv": "sm_70"`, `"volta": "sm_70"`
     - `"gtx1080ti": "sm_61"`, `"gtx1080": "sm_61"`, `"p40": "sm_61"`, `"teslap40": "sm_61"`, `"titanxp": "sm_61"`, `"pascal": "sm_61"`
     - `"p100": "sm_60"`, `"teslap100": "sm_60"`
     - `"m40": "sm_52"`, `"teslam40": "sm_52"`, `"maxwell": "sm_52"`
   - **AMD retail card & architecture aliases:**
     - `"rx9070xt": "gfx1201"`, `"rx9070": "gfx1200"`, `"r9700": "gfx1201"`
     - `"strix-halo": "gfx1151"`, `"ryzen-ai-max": "gfx1151"`, `"ryzen-ai-395": "gfx1151"`, `"ryzen-ai-300": "gfx1150"`, `"radeon-890m": "gfx1150"`
     - `"rx7900xtx": "gfx1100"`, `"rx7900xt": "gfx1100"`, `"rx7900gre": "gfx1100"`, `"w7900": "gfx1100"`
     - `"rx7800xt": "gfx1101"`, `"rx7700xt": "gfx1101"`, `"w7800": "gfx1101"`, `"w7700": "gfx1101"`
     - `"rx7600xt": "gfx1102"`, `"rx7600": "gfx1102"`
     - `"radeon-780m": "gfx1103"`, `"z1-extreme": "gfx1103"`
     - `"rx6950xt": "gfx1030"`, `"rx6900xt": "gfx1030"`, `"rx6800xt": "gfx1030"`, `"rx6800": "gfx1030"`, `"w6800": "gfx1030"`, `"rdna2": "gfx1030"`
     - `"rx6700xt": "gfx1031"`, `"rx6600xt": "gfx1032"`, `"rx6600": "gfx1032"`, `"radeon-680m": "gfx1035"`
     - `"mi300a": "gfx942"`, `"cdna2": "gfx90a"`, `"mi100": "gfx908"`, `"cdna1": "gfx908"`
     - `"mi50": "gfx906"`, `"mi60": "gfx906"`, `"radeon-vii": "gfx906"`, `"vega20": "gfx906"`, `"vega64": "gfx900"`, `"vega56": "gfx900"`
   - **Intel & CPU/Accelerator aliases:**
     - `"arc a750": "arc-a750"`, `"arc a730m": "arc-a730m"`, `"arc a580": "arc-a580"`, `"arc b770": "arc-b770"`, `"max 1100": "data-center-max-1100"`, `"lunar-lake": "arc-igpu-lunar-lake"`, `"meteor-lake": "arc-igpu-meteor-lake"`, `"arrow-lake": "arc-igpu-arrow-lake"`, `"panther-lake": "arc-igpu-panther-lake"`
     - `"zen5": "x86-64-amd-zen5"`, `"zen4": "x86-64-amd-zen4"`, `"zen3": "x86-64-amd-zen3"`, `"zen2": "x86-64-amd-zen2"`, `"avx2": "x86-64-avx2"`, `"avx512": "x86-64-avx512"`, `"amx": "x86-64-amx-int8"`

3. **Mirror `hw_archs` in `data/taxonomy.extensions.json`:**
   Keep `data/taxonomy.extensions.json` valid JSON with `"hw_archs"` populated with the scraper-discovered archs so `merge_extensions` remains clean.

#### Acceptance Criteria (H1-TAX)
- `python3 -c "import json; t = json.load(open('data/taxonomy.json')); assert len(t['hw_aliases']) >= 100; assert 'm4-ultra' in t['hw_archs']['apple']; assert 'gfx1035' in t['hw_archs']['amd']"` exits 0.

---

### Agent H1-APPLE: `apple-silicon-expansion`

**Write Scope:** `scrapers/sources/apple_integrations.py`, `scrapers/cache/apple_integrations/**`

#### Tasks

1. **Copy already-cached `ollama/docs/gpu.mdx` and `llama.cpp/docs/build.md` into `scrapers/cache/apple_integrations/`** (if needed by new URLs in `apple_integrations.py`, or reuse the 5 existing cached URLs in `scrapers/cache/apple_integrations/` plus `gpu.mdx` copied from `scrapers/cache/curated_combos/raw.githubusercontent.com_ollama_ollama_main_docs_gpu.mdx.a4810672b2471489ee6f71c6.cache` and `Qwen3-32B-4bit` / `Llama-3.3-70B-Instruct-4bit` / `gemma-3-27b-it-4bit` / `DeepSeek-R1-Distill-Qwen-32B-4bit` / `Mistral-Small-24B-Instruct-2501-4bit` copied from `scrapers/cache/curated_combos/`).
   - **Why:** Copying those `.cache` files into `scrapers/cache/apple_integrations/` ensures `python3 scrapers/run_all.py --offline --only apple_integrations` runs with **0 network calls and 0 offline-misses**.

2. **Expand `scrapers/sources/apple_integrations.py` to cover all 18+ Apple Silicon M1–M5 chips & extra facts:**
   Using real, verbatim-verified quotes from the cached upstream docs:
   - **`vllm-metal` (`https://raw.githubusercontent.com/vllm-project/vllm-metal/main/README.md`):**
     - `m1`: quote `"vLLM Metal is a plugin that enables vLLM to run on Apple Silicon Macs using MLX as the primary compute backend."` (`status="solved"`, `source_kind="scraped"`, `missing=["model"]`).
     - `m5`: quote `"vLLM Metal now uses M5 NAX tensor units to accelerate MHA, GQA, and MQA prefill."` (`status="solved"`, `source_kind="scraped"`, `missing=["model"]`).
     - `m5-pro`: quote `"DiffusionGemma now supports Jev-like System 1 decisions on Metal, with median decision latency under 0.2 s on an M5 Pro."` (`status="solved"`, `source_kind="scraped"`, `missing=["model"]`, `hw_name="Apple M5 Pro (Metal)"`).
     - `m1` + `qwen3` (`model_family="qwen3"`, `runtime="vllm-metal"`, `quant="mlx-8bit"`, `missing=[]`, `source_kind="scraped"`): quote `"Qwen3.8 now runs on Metal! \`mlx-community/Qwen3.8-27B-8bit\` serves a 27B hybrid SDPA + GDN linear model on a single Apple Silicon Mac."`
     - `m1` + `stable-diffusion` (`model_family="stable-diffusion"`, `runtime="vllm-metal"`, `missing=[]`, `source_kind="scraped"`): quote `"[Text-to-image generation](https://docs.vllm.ai/projects/vllm-metal/en/latest/omni/#text-to-image) is now supported through vLLM-Omni, starting with SDXL."`
   - **`ollama` (`https://raw.githubusercontent.com/ollama/ollama/main/docs/gpu.mdx`):**
     - Emit `scraped` (`m1`) and `derived` (`missing=["model"]`) rows for Apple Metal across the M-series chip tiers (`m1`, `m1-pro`, `m1-max`, `m1-ultra`, `m2`, `m2-pro`, `m2-max`, `m2-ultra`, `m3`, `m3-pro`, `m3-max`, `m3-ultra`, `m4`, `m4-pro`, `m4-max`, `m4-ultra`, `m5`, `m5-pro`, `m5-max`) backed by the verbatim quote `"Ollama supports GPU acceleration on Apple devices via the Metal API."` from `docs/gpu.mdx`, with accurate `hw_name` and `hw_extra` (`{"backend": "Metal", "unified_memory_gb": ...}`).
   - **`mlx` & `mlx-lm` (`https://raw.githubusercontent.com/ml-explore/mlx/main/README.md` & `mlx-lm/main/README.md`):**
     - Emit hardware-level support (`model_family="*"`, `missing=["model"]`) for `mlx` and `mlx-lm` across the M1–M5 families (`m1` through `m5-max`, plus `m4-ultra`) with `source_kind="scraped"` on `m1` and `source_kind="derived"` (`created_by="derived"`) on the specific M-series chips (`m1-pro`, `m1-max`, `m1-ultra`, `m2`, `m2-pro`, `m2-max`, `m2-ultra`, `m3`, `m3-pro`, `m3-max`, `m3-ultra`, `m4`, `m4-pro`, `m4-max`, `m4-ultra`, `m5`, `m5-pro`, `m5-max`), explicitly noting in `notes` that upstream MLX targets all Apple Silicon M-series GPUs via Metal and recording each chip's standard unified memory tier in `hw_extra`.

#### Acceptance Criteria (H1-APPLE)
- `python3 scrapers/run_all.py --offline --only apple_integrations` exits 0 with **0 rejects**, **0 offline-misses**, and covers **all 18+ Apple M-series architectures** (`m1` through `m5-max` + `m4-ultra`).

---

### Agent H1-BACKENDS: `ollama-and-sycl-scrapers`

**Write Scope:** `scrapers/sources/llama_cpp_backends.py`, `scrapers/sources/vllm_install.py`, `scrapers/cache/llama_cpp_backends/**`

#### Tasks

1. **Copy cached `ollama/docs/gpu.mdx` into `scrapers/cache/llama_cpp_backends/`:**
   Copy `scrapers/cache/curated_combos/raw.githubusercontent.com_ollama_ollama_main_docs_gpu.mdx.a4810672b2471489ee6f71c6.cache` into `scrapers/cache/llama_cpp_backends/` so `llama_cpp_backends.py` can also parse `ollama/docs/gpu.mdx` in `--offline` mode without touching `scrapers/run_all.py`.

2. **Extract Already-Quoted Intel GPUs in `scrapers/sources/llama_cpp_backends.py`:**
   - In `docs/backend/SYCL.md` (lines 230–247 of `llama_cpp_backends.py`), the fetched table rows already contain verbatim quotes for:
     - `data-center-max-1100`: `"| Intel Data Center Max Series  | Support | Max 1550, 1100                        |"` → emit `intel/data-center-max-1100/*/llama_cpp` (`status="solved"`, `source_kind="scraped"`).
     - `arc-a750`: `"| Intel Arc A-Series            | Support | Arc A770, Arc A730M, Arc A750         |"` → emit `intel/arc-a750/*/llama_cpp` (`status="solved"`, `source_kind="scraped"`).
     - `arc-a730m`: same quote → emit `intel/arc-a730m/*/llama_cpp` (`status="solved"`, `source_kind="scraped"`).
     - `arc-igpu-arrow-lake`: `"| Intel built-in Arc GPU        | Support | built-in Arc GPU in Meteor Lake, Arrow Lake, Lunar Lake |"` → emit `intel/arc-igpu-arrow-lake/*/llama_cpp` (`status="solved"`, `source_kind="scraped"`).
     - `arc-igpu-lunar-lake`: same quote → emit `intel/arc-igpu-lunar-lake/*/llama_cpp` (`status="solved"`, `source_kind="scraped"`).
   - In `docs/build.md` (§Metal Build, line 207):
     - Alongside `apple/m1/*/llama_cpp`, emit `derived` (`missing=["model"]`) `llama.cpp` Metal rows for `m1-pro`, `m1-max`, `m1-ultra`, `m2`, `m2-pro`, `m2-max`, `m2-ultra`, `m3`, `m3-pro`, `m3-max`, `m3-ultra`, `m4`, `m4-pro`, `m4-max`, `m5`, `m5-pro`, `m5-max` using the verbatim quote `"On MacOS, Metal is enabled by default. Using Metal makes the computation run on the GPU."`

3. **Extract the Full NVIDIA & AMD Hardware Tables from `ollama/docs/gpu.mdx` in `scrapers/sources/llama_cpp_backends.py`:**
   Fetch `https://raw.githubusercontent.com/ollama/ollama/main/docs/gpu.mdx` (cached!) and emit `status="solved"`, `source_kind="scraped"`, `runtime="ollama"`, `model_family="*"`, `missing=["model"]` rows with verbatim table-row quotes for:
   - **NVIDIA (`ollama`):**
     - `sm_121`: `"| 12.1               | NVIDIA              | \`GB10 (DGX Spark)\`"` (`hw_name="NVIDIA GB10 (DGX Spark, CC 12.1)"`)
     - `sm_120`: `"| 12.0               | GeForce RTX 50xx    | \`RTX 5060\` \`RTX 5060 Ti\` \`RTX 5070\` \`RTX 5070 Ti\` \`RTX 5080\` \`RTX 5090\`"`
     - `sm_90`: `"| 9.0                | NVIDIA              | \`H200\` \`H100\`"`
     - `sm_89`: `"| 8.9                | GeForce RTX 40xx    | \`RTX 4090\` \`RTX 4080 SUPER\` \`RTX 4080\`"`
     - `sm_86`: `"| 8.6                | GeForce RTX 30xx    | \`RTX 3090 Ti\` \`RTX 3090\` \`RTX 3080 Ti\` \`RTX 3080\`"`
     - `sm_80`: `"| 8.0                | NVIDIA              | \`A100\` \`A30\`"`
     - `sm_75`: `"| 7.5                | GeForce GTX/RTX     | \`GTX 1650 Ti\` \`TITAN RTX\` \`RTX 2080 Ti\` \`RTX 2080\`"`
     - `sm_70`: `"| 7.0                | NVIDIA              | \`TITAN V\` \`V100\` \`Quadro GV100\`"`
     - `sm_61`: `"| 6.1                | GeForce GTX         | \`GTX 1080 Ti\` \`GTX 1080\` \`GTX 1070 Ti\`"` (plus `Tesla P40`)
     - `sm_60`: `"| 6.0                | NVIDIA              | \`Tesla P100\` \`Quadro GP100\`"`
     - `sm_52`: `"| 5.2                | GeForce GTX         | \`GTX TITAN X\` \`GTX 980 Ti\`"` (plus `Tesla M40`)
   - **AMD (`ollama`):**
     - `gfx908`: `"| gfx908 | Radeon Instinct MI100 |"`
     - `gfx90a`: `"| gfx90a | Radeon Instinct MI210/MI250 |"`
     - `gfx942`: `"| gfx942 | Radeon Instinct MI300X/MI300A |"`
     - `gfx950`: `"| gfx950 | Radeon Instinct MI350X |"`
     - `gfx1030`: `"| gfx1030 | Radeon PRO V620 |"`
     - `gfx1034` (`status="rejected"`, `source_kind="scraped"`): quote `"For example The Radeon RX 5400 is \`gfx1034\` (also known as 10.3.4) however, ROCm does not currently support this target."` (`notes="Ollama ROCm does not natively support gfx1034; requires HSA_OVERRIDE_GFX_VERSION=10.3.0 workaround."`)
     - `gfx1100`: `"| gfx1100 | Radeon PRO W7900 |"`
     - `gfx1101`: `"| gfx1101 | Radeon PRO W7700 |"`
     - `gfx1102`: `"| gfx1102 | Radeon RX 7600 |"`
     - `gfx1150`: `"| gfx1150 | Ryzen AI 9 HX 375 |"`
     - `gfx1151`: `"| gfx1151 | Ryzen AI Max+ 395 |"`
     - `gfx1200`: `"| gfx1200 | Radeon RX 9070 |"`
     - `gfx1201`: `"| gfx1201 | Radeon RX 9070 XT |"`

4. **Expand `scrapers/sources/vllm_install.py` for Derived CUDA CC >= 7.5 Architectures:**
   - `gpu.cuda.inc.md` states: `"- GPU: compute capability 7.5 or higher (e.g., T4, RTX20xx, A100, L4, H100, B200, etc.)"`.
   - In addition to the 5 explicitly named example cards (`sm_75`, `sm_80`, `sm_89`, `sm_90`, `sm_100`), emit `source_kind="derived"`, `missing=["model"]` rows for the remaining taxonomy architectures ≥ 7.5 (`sm_86`, `sm_87`, `sm_90a`, `sm_100a`, `sm_103`, `sm_120`, `sm_121`) and `status="rejected"`, `source_kind="derived"` for `sm_60`, `sm_61`, `sm_70` (`notes="vLLM CUDA prebuilt wheels require compute capability 7.5 or higher; Pascal (sm_60/sm_61) and Volta (sm_70) are below the CC 7.5 floor."`).

#### Acceptance Criteria (H1-BACKENDS)
- `python3 scrapers/run_all.py --offline --only llama_cpp_backends vllm_install` exits 0 with **0 rejects** and **0 offline-misses**.
- `sm_60`, `sm_61`, `sm_70`, `sm_87`, `sm_90a`, `sm_100a`, `sm_103`, `sm_121`, `gfx908`, `gfx1034`, `gfx1102`, `arc-a750`, `arc-a730m`, and `data-center-max-1100` all have verified rows.

---

### Agent H1-CURATED: `curated-model-hw-matrix`

**Write Scope:** `scrapers/sources/curated_combos.py`

#### Tasks

Expand `SPECS` in `scrapers/sources/curated_combos.py` using **only the 15 already-cached upstream URLs** declared at lines 17–35 of `curated_combos.py` (`LLAMA_CPP_BUILD`, `LLAMA_CPP_SYCL`, `VLLM_GPU`, `MLX_LM_README`, `OLLAMA_GPU`, `HF_QWEN3_32B`, `HF_DEEPSEEK_R1`, `HF_GPT_OSS_20B`, `HF_MISTRAL_24B`, `HF_GEMMA3_GGUF`, `HF_LLAMA3_GGUF`, `HF_MLX_QWEN3`, `HF_MLX_LLAMA3`, `HF_MLX_GEMMA3`, `HF_MLX_DEEPSEEK`, `HF_MLX_MISTRAL`) so that `python3 scrapers/run_all.py --offline --only curated_combos` runs 100% offline with zero network calls!

Add **45+ new `source_kind: "hand"` model-specific rows** across the missing hardware tiers:

1. **Apple Silicon Model × Runtime Matrix (Closing the Apple Gap):**
   - **`m1` (8–16 GB):**
     - `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`, pointer `HF_MLX_QWEN3`)
     - `gemma-3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `HF_GEMMA3_GGUF`)
     - `llama-3` × `ollama` (`solved`, `Q4_K_M`, pointer `OLLAMA_GPU`, quote `"Ollama supports GPU acceleration on Apple devices via the Metal API."`)
   - **`m1-pro` (32 GB) & `m1-max` (64 GB) & `m1-ultra` (128 GB):**
     - `m1-pro`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`), `mistral` × `mlx-lm` (`solved`, `mlx-4bit`)
     - `m1-max`: `llama-3` × `mlx-lm` (`solved`, `mlx-4bit`, 64 GB), `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`)
     - `m1-ultra`: `llama-3` × `mlx-lm` (`solved`, `mlx-4bit`, 128 GB), `deepseek` × `mlx-lm` (`solved`, `mlx-4bit`, 128 GB)
   - **`m2` (16–24 GB), `m2-pro` (32 GB), `m2-max` (96 GB), `m2-ultra` (192 GB):**
     - `m2`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`), `gemma-3` × `llama.cpp` (`solved`, `Q4_K_M`)
     - `m2-pro`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`), `mistral` × `mlx-lm` (`solved`, `mlx-4bit`)
     - `m2-max`: `llama-3` × `mlx-lm` (`solved`, `mlx-4bit`, 96 GB), `deepseek` × `mlx-lm` (`solved`, `mlx-4bit`)
     - `m2-ultra`: `deepseek` × `mlx-lm` (`solved`, `mlx-4bit`, 192 GB), `llama-3` × `llama.cpp` (`solved`, `Q4_K_M`, 192 GB), `qwen3` × `ollama` (`solved`, `Q4_K_M`)
   - **`m3` (16–24 GB), `m3-pro` (36 GB), `m3-max` (128 GB), `m3-ultra` (256–512 GB):**
     - `m3`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`)
     - `m3-pro`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`), `gemma-3` × `mlx-lm` (`solved`, `mlx-4bit`)
     - `m3-max`: add `llama.cpp` (`qwen3`, `Q4_K_M`, pointer `HF_QWEN3_32B`) and `ollama` (`gpt-oss`, `Q4_K_M`, pointer `HF_GPT_OSS_20B`) so `m3-max` isn't `mlx-lm`-only!
     - `m3-ultra`: `deepseek` × `mlx-lm` (`solved`, `mlx-4bit`, 512 GB unified memory), `llama-3` × `mlx-lm` (`solved`, `mlx-4bit`), `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`)
   - **`m4` (16–32 GB), `m4-pro` (48–64 GB), `m4-max` (128 GB), `m4-ultra` (256 GB):**
     - `m4`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`), `gemma-3` × `llama.cpp` (`solved`, `Q4_K_M`), `gpt-oss` × `ollama` (`solved`, `Q4_K_M`)
     - `m4-pro`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`, 48 GB), `deepseek` × `mlx-lm` (`solved`, `mlx-4bit`, 48 GB), `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`)
     - `m4-max`: add `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `HF_QWEN3_32B`) and `gpt-oss` × `ollama` (`solved`, `Q4_K_M`, pointer `HF_GPT_OSS_20B`)
     - `m4-ultra`: `deepseek` × `mlx-lm` (`solved`, `mlx-4bit`, 256 GB), `llama-3` × `mlx-lm` (`solved`, `mlx-4bit`)
   - **`m5` (16–32 GB), `m5-pro` (48–64 GB), `m5-max` (128 GB):**
     - `m5`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`)
     - `m5-pro`: `qwen3` × `mlx-lm` (`solved`, `mlx-4bit`, 64 GB)
     - `m5-max`: `llama-3` × `mlx-lm` (`solved`, `mlx-4bit`, 128 GB), `deepseek` × `mlx-lm` (`solved`, `mlx-4bit`, 128 GB)

2. **NVIDIA, AMD & Intel Missing Model-Specific Combos:**
   - **NVIDIA `sm_121` (DGX Spark / GB10 128 GB):** `qwen3` × `ollama` (`solved`, `Q4_K_M`, pointer `OLLAMA_GPU`, quote `"| 12.1               | NVIDIA              | \`GB10 (DGX Spark)\`"`), `llama-3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `HF_LLAMA3_GGUF`)
   - **NVIDIA `sm_100` (B200 180 GB):** `deepseek` × `vllm` (`solved`, `fp8`, pointer `HF_DEEPSEEK_R1`), `qwen3` × `vllm` (`solved`, `bf16`, pointer `HF_QWEN3_32B`)
   - **NVIDIA `sm_80` (A100 80 GB):** `llama-3` × `vllm` (`solved`, `bf16`, pointer `VLLM_GPU`), `qwen3` × `vllm` (`solved`, `bf16`, pointer `HF_QWEN3_32B`)
   - **NVIDIA `sm_75` (RTX 2080 Ti / T4):** `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `HF_QWEN3_32B`), `gemma-3` × `ollama` (`solved`, `Q4_K_M`, pointer `OLLAMA_GPU`)
   - **NVIDIA `sm_61` (Tesla P40 24 GB / GTX 1080 Ti):** `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `LLAMA_CPP_BUILD`), `llama-3` × `ollama` (`solved`, `Q4_K_M`, pointer `OLLAMA_GPU`, quote `"|                    | Tesla               | \`P40\` \`P4\`"`)
   - **AMD `gfx90a` (MI250X 128 GB):** `qwen3` × `vllm` (`solved`, `bf16`, pointer `HF_QWEN3_32B`), `llama-3` × `ollama` (`solved`, `Q4_K_M`, pointer `OLLAMA_GPU`, quote `"| gfx90a | Radeon Instinct MI210/MI250 |"`)
   - **AMD `gfx950` (MI350X 288 GB):** `deepseek` × `vllm` (`solved`, `fp8`, pointer `HF_DEEPSEEK_R1`)
   - **AMD `gfx1201` (RX 9070 XT 16 GB):** `qwen3` × `ollama` (`solved`, `Q4_K_M`, pointer `OLLAMA_GPU`, quote `"| gfx1201 | Radeon RX 9070 XT |"`), `gemma-3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `HF_GEMMA3_GGUF`)
   - **AMD `gfx1030` (RX 6800 XT / 6900 XT 16 GB):** `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `LLAMA_CPP_BUILD`), `llama-3` × `ollama` (`solved`, `Q4_K_M`, pointer `OLLAMA_GPU`)
   - **AMD `gfx906` (MI50 / MI60 32 GB / Radeon VII):** `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `LLAMA_CPP_BUILD`, quote `"This provides GPU acceleration on HIP-supported AMD GPUs."`)
   - **Intel `data-center-max-1550` (Max 1550 128 GB):** `qwen3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `LLAMA_CPP_SYCL`, quote `"| Intel Data Center Max Series  | Support | Max 1550, 1100                        |"`), `llama-3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `LLAMA_CPP_SYCL`)
   - **Intel `arc-a750` (8 GB):** `gemma-3` × `llama.cpp` (`solved`, `Q4_K_M`, pointer `LLAMA_CPP_SYCL`, quote `"| Intel Arc A-Series            | Support | Arc A770, Arc A730M, Arc A750         |"`)

#### Acceptance Criteria (H1-CURATED)
- `python3 scrapers/run_all.py --offline --only curated_combos` exits 0 with **0 rejects**, **0 offline-misses**, and **≥ 75 rows**.

---

### Agent H1-CONTRIB: `user-hw-submission-flow`

**Write Scope:** `web/js/app.js`, `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/submit-combo.yml`, `scripts/ingest_combo.py` *(new)*

#### Tasks

1. **Improve Vendor Inference for User-Typed Hardware in `web/js/app.js`:**
   - In `resolveVendorForArch(arch)` (`web/js/app.js` lines 163–185):
     - Expand prefix/pattern rules so users typing unlisted hardware into Lookup get the right `hw_vendor` in their 4-segment ID (`{hw_vendor}/{hw_arch}/{model}/{runtime}`) when voting or submitting a pointer:
       - `nvidia`: `/^(sm_|rtx|gtx|tesla|quadro|jetson|dgx|gb[12]0|h[12]00|a[1346]0|b[123]00|l40|t4|v100|p100|p40|m40)/`
       - `amd`: `/^(gfx|rx-?[0-9]|radeon|instinct|mi[0-9]|strix|ryzen-ai|w[67][0-9]{3}|r9700)/`
       - `intel`: `/^(arc-|data-center-max|flex-|intel-|gaudi|xeon|core-ultra|lunar-lake|meteor-lake|arrow-lake|panther-lake)/`
       - `apple`: `/^(m[1-9]($|[-_])|a1[5-9]($|[-_])|apple|mac-|macbook)/`
       - `qualcomm`: `/^(snapdragon|hexagon|adreno)/`
       - `arm-cpu`: `/^(aarch64|arm64|armv[89]|graviton|ampereone|grace-cpu|cortex)/`
       - `x86-cpu`: `/^(x86|avx|sse|amx|zen[2-6]|epyc)/`

2. **Create `scripts/ingest_combo.py` (CLI Helper for Maintainers & Contributors to Add Hardware / Combos):**
   - A stdlib-only Python CLI script that lets a contributor or maintainer add a new hardware architecture + combo row in one validated command, or ingest a JSON/YAML issue payload:
     ```bash
     python3 scripts/ingest_combo.py \
       --vendor apple --arch m4-ultra --hw-name "Apple M4 Ultra" \
       --model qwen3 --runtime mlx-lm --status solved --quant mlx-4bit \
       --pointer "https://huggingface.co/mlx-community/Qwen3-32B-4bit" \
       --quote "from mlx_lm import load, generate" \
       --notes "Qwen3-32B-4bit runs on Apple M4 Ultra via mlx-lm." \
       --register-taxonomy
     ```
   - Validates the constructed row via `pipeline.schema.canonicalize()` and `pipeline.schema.validate()`.
   - When `--register-taxonomy` is passed (and `arch` is not yet in `data/taxonomy.json` `hw_archs[vendor]`), appends `arch` (and optional `--alias`) into `data/taxonomy.extensions.json` (or `data/taxonomy.json` if `--write-taxonomy` is passed).
   - Appends/merges the validated row into `data/rows/<vendor>.jsonl` (sorted by `id`) and supports `--dry-run`.

3. **Update `.github/ISSUE_TEMPLATE/submit-combo.yml` & `CONTRIBUTING.md`:**
   - In `.github/ISSUE_TEMPLATE/submit-combo.yml`:
     - Add an optional `hw_name_and_extra` input (`Hardware Display Name & Specs (optional)`, e.g. `"Apple M4 Ultra (256 GB unified memory)"` or `"vram_gb: 24, rocm_min: 7.0"`) and an optional `hw_aliases` input (`Search Aliases (optional)`, e.g. `"m4 ultra, mac studio m4 ultra"`) so users submitting a brand-new card can provide its human label, memory tier, and search aliases.
   - In `CONTRIBUTING.md`:
     - Add a dedicated section **"Adding a New Hardware Architecture or Alias"** explaining:
       1. How users can immediately vote on any unlisted hardware slug in the Lookup UI (`Want this`) or submit a pointer via the 1-click **"I got this working — submit pointer"** button.
       2. How contributors can register a new `hw_arch` and `hw_aliases` in `data/taxonomy.json` (or via `python3 scripts/ingest_combo.py --register-taxonomy`).

#### Acceptance Criteria (H1-CONTRIB)
- `node --check web/js/app.js` exits 0.
- `python3 scripts/ingest_combo.py --help` and a `--dry-run` invocation exit 0 and validate cleanly against `pipeline/schema.py`.

---

## 3. Detailed Wave 2 Integrator Specification

### Agent H2-INT: `hardware-integrator-verify`

**Runs ONLY after H1-TAX, H1-APPLE, H1-BACKENDS, H1-CURATED, and H1-CONTRIB have all completed.**

#### Steps (In Exact Order)

1. **Run All Scrapers Offline & Validate Raw Output:**
   ```bash
   python3 scrapers/run_all.py --offline
   python3 scrapers/validate_raw.py
   ```
   Verify **0 rejects** across all scraper sources.

2. **Rebuild Dataset & Refresh Offline Snapshot:**
   ```bash
   python3 pipeline/build.py --check
   node web/tools/inline-snapshot.mjs
   ```

3. **Run Full Test Suite:**
   ```bash
   python3 pipeline/tests/test_pipeline.py
   python3 api/tests/test_api.py
   node --test web/tests/smoke.mjs
   ```

4. **Run the Hardware Completeness Verification Gate (Must Exit 0):**
   ```bash
   python3 -c '
   import json, sys

   tax = json.load(open("data/taxonomy.json"))
   combos = json.load(open("data/combos.json"))
   rows = combos["rows"]

   errs = []

   # 1. Every Apple M1-M5 taxonomy arch must have at least 1 row AND at least 1 model-specific row
   apple_archs = tax["hw_archs"]["apple"]
   apple_rows_by_arch = {}
   apple_model_rows_by_arch = {}
   for r in rows:
       if r["hw_vendor"] == "apple":
           apple_rows_by_arch.setdefault(r["hw_arch"], []).append(r)
           if r["model_family"] != "*":
               apple_model_rows_by_arch.setdefault(r["hw_arch"], []).append(r)

   for a in ["m1","m1-pro","m1-max","m1-ultra","m2","m2-pro","m2-max","m2-ultra",
             "m3","m3-pro","m3-max","m3-ultra","m4","m4-pro","m4-max","m4-ultra",
             "m5","m5-pro","m5-max"]:
       if a not in apple_rows_by_arch:
           errs.append(f"Apple arch {a} still has 0 rows")
       if a not in apple_model_rows_by_arch:
           errs.append(f"Apple arch {a} has 0 model-specific rows")

   # 2. Zero orphan row architectures (every hw_arch in rows must exist in taxonomy.json hw_archs)
   for r in rows:
       v = r["hw_vendor"]
       a = r["hw_arch"]
       if a not in tax["hw_archs"].get(v, []):
           errs.append(f"Orphan row arch not in taxonomy.json: {v}/{a}")

   # 3. Chimeric typo slug rv64-spacemit-s390x must be gone
   if "rv64-spacemit-s390x" in tax["hw_archs"].get("arm-cpu", []):
       errs.append("Typo slug rv64-spacemit-s390x still in arm-cpu taxonomy")

   # 4. Alias count & Apple alias check
   aliases = tax.get("hw_aliases", {})
   for k in ["m4_pro", "m3_max", "dgx-spark", "rtx4070", "a6000", "rx7900xtx", "mi50", "strix-halo"]:
       if k not in aliases:
           errs.append(f"Missing expected hw_alias: {k}")

   if errs:
       print("HARDWARE GATE FAILED:", *sorted(set(errs)), sep="\n  - ")
       sys.exit(1)

   print(f"HARDWARE GATE PASSED: {len(rows)} total rows, {len(apple_rows_by_arch)} Apple archs active, {len(aliases)} hw_aliases.")
   '
   ```
