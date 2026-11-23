# Missing Hardware Analysis (`canirun`)

An audit of [taxonomy.json](file:///Users/windows/Model%20support%20for%20hardware%20site/data/taxonomy.json), [data/rows/*.jsonl](file:///Users/windows/Model%20support%20for%20hardware%20site/data/rows), and the scraper corpus in [scrapers/sources/](file:///Users/windows/Model%20support%20for%20hardware%20site/scrapers/sources) reveals **four distinct layers of missing hardware**:

1. **Taxonomy Ghosts (44 of 82 taxonomy `hw_archs` have 0 rows):** Defined in [taxonomy.json](file:///Users/windows/Model%20support%20for%20hardware%20site/data/taxonomy.json#L80-L103) and shown in UI dropdowns, but completely absent from `data/rows/*.jsonl`.
2. **Wildcard-Only Hardware (50 active `hw_archs` have only `*` rows):** Have backend-level `"model_family": "*"` context rows (`missing: ["model"]`), meaning **every model-specific lookup returns a miss (`partial-context`)**.
3. **Orphan Row Architectures (26 `hw_archs` in `data/rows/` are missing from `taxonomy.json`):** Emitted by scrapers (e.g., `gfx1035`, `snapdragon-x2-elite`, `ascend-910b`, `x86-64-amd-zen5`), so they do not appear in canonical vendor architecture lists in [taxonomy.json](file:///Users/windows/Model%20support%20for%20hardware%20site/data/taxonomy.json#L80-L103).
4. **Real-World Hardware & Alias Gaps:** Widely used local-inference hardware and search aliases not yet in `taxonomy.json` at all (e.g., `m4-ultra`, `m5-ultra`, Apple `a17-pro`/`a18-pro`, NVIDIA `gb10` DGX Spark / Jetson `sm_87`, consumer GPU aliases like `rtx 3060`, `rtx 4070`, `rx 7800 xt`, and Apple device names like `mac studio`, `macbook pro`).

---

## Coverage Summary by Vendor

| Vendor | Taxonomy `hw_archs` | Active in `data/rows/` | **Missing (0 Rows)** | Active w/ **Only `*` Rows** (0 Model Combos) | Active w/ Specific Models | Row Archs Missing from Taxonomy |
|---|---:|---:|---:|---:|---:|---:|
| **Apple** (`apple`) | 18 | 4 | **14 (78%)** | 2 (`m1`, `m5`) | 2 (`m3-max`, `m4-max`) | 0 |
| **NVIDIA** (`nvidia`) | 15 | 7 | **8 (53%)** | 3 (`sm_75`, `sm_80`, `sm_100`) | 4 (`sm_86`, `sm_89`, `sm_90`, `sm_120`) | 0 |
| **Intel** (`intel`) | 14 | 11 | **7 (50%)** | 9 | 2 (`arc-a770`, `arc-b580`) | 4 |
| **AMD** (`amd`) | 17 | 12 | **6 (35%)** | 9 | 3 (`gfx1100`, `gfx1151`, `gfx942`) | 1 (`gfx1035`) |
| **ARM CPU** (`arm-cpu`) | 5 | 3 | **3 (60%)** | 3 | 0 | 1 (`aarch64-bf16`) |
| **x86 CPU** (`x86-cpu`) | 6 | 8 | **3 (50%)** | 7 | 1 (`generic` — HF unjoined) | 5 |
| **Qualcomm** (`qualcomm`) | 6 | 8 | **2 (33%)** | 8 | 0 | 4 |
| **Other** (`other`) | 1 | 11 | **1 (100%)** | 9 | 2 (`ascend-910b`, `et-soc-1`) | 11 |
| **Total** | **82** | **64** | **44** | **50** | **14** | **26** |

---

## 1. Apple Hardware Gaps (Why Apple Is Super Incomplete)

> [!IMPORTANT]
> Out of **18 Apple Silicon chips** in [taxonomy.json](file:///Users/windows/Model%20support%20for%20hardware%20site/data/taxonomy.json#L96-L97), **14 have zero rows** in [apple.jsonl](file:///Users/windows/Model%20support%20for%20hardware%20site/data/rows/apple.jsonl), and **zero Apple aliases** exist in `hw_aliases`.

### Why this happens in the pipeline
1. **Everything collapses to `m1`:** Both [apple_integrations.py](file:///Users/windows/Model%20support%20for%20hardware%20site/scrapers/sources/apple_integrations.py#L19-L74) and [llama_cpp_backends.py](file:///Users/windows/Model%20support%20for%20hardware%20site/scrapers/sources/llama_cpp_backends.py#L207-L212) hardcode `"hw_arch": "m1"` whenever upstream docs say `"Apple Silicon"` or `"macOS"`, leaving `m2`, `m3`, `m4`, and `m5` families empty.
2. **`hf_models` MLX repos get tagged as `x86-cpu/generic`:** In [hf_models.py](file:///Users/windows/Model%20support%20for%20hardware%20site/scrapers/sources/hf_models.py#L236), scraped `mlx-lm` repos are emitted with `hw_vendor="x86-cpu", hw_arch="generic", missing=["hw"]`, and [join.py](file:///Users/windows/Model%20support%20for%20hardware%20site/pipeline/join.py#L38-L72) never joins them to Apple Silicon because no upstream doc quote simultaneously names a chip (`m1`–`m5`) and a model family.
3. **Zero `hw_aliases` for Apple:** Typing `m4 pro`, `mac studio`, `macbook pro`, `apple silicon`, or `metal` has no entry in [taxonomy.json `hw_aliases`](file:///Users/windows/Model%20support%20for%20hardware%20site/data/taxonomy.json#L104-L115) (`m4_pro` with an underscore even appears as an example in [CONTRACT.md](file:///Users/windows/Model%20support%20for%20hardware%20site/CONTRACT.md#L130) despite the taxonomy slug being `m4-pro`).

### Complete Apple Missing Hardware List

| Category | Missing Slugs / Items | Typical Memory Tiers & Local LLM Relevance |
|---|---|---|
| **In Taxonomy, 0 Rows (14 chips)** | `m1-pro`, `m1-max`, `m1-ultra`<br>`m2`, `m2-pro`, `m2-max`, `m2-ultra`<br>`m3`, `m3-pro`, `m3-ultra`<br>`m4`, `m4-pro`<br>`m5-pro`, `m5-max` | • **Base (`m2`, `m3`, `m4`):** 8–32 GB unified memory (7B–14B 4-bit models)<br>• **Pro (`m1-pro`..`m5-pro`):** 16–64 GB unified memory (14B–32B 4-bit/8-bit)<br>• **Max (`m1-max`, `m2-max`, `m5-max`):** 32–128 GB unified memory (32B–70B+ 4-bit)<br>• **Ultra (`m1-ultra`, `m2-ultra`, `m3-ultra`):** 64–512 GB unified memory (70B–671B DeepSeek V3/R1 MoE, Llama 3.3 70B FP16, Qwen3-235B) |
| **In `apple.jsonl`, 0 Model Rows (2 chips)** | `m1` (7 `*` rows only)<br>`m5` (1 `*` row for `vllm-metal` only) | • `m1` has `*` rows for `llama.cpp`, `mlx`, `mlx-lm`, `ollama`, `vllm`, `vllm-metal`, `mlc-llm`, but **0 specific model rows**.<br>• `m5` is missing `llama.cpp`, `mlx`, `mlx-lm`, `ollama`, and all model rows. |
| **In `apple.jsonl`, Partial Only (2 chips)** | `m3-max` (only `qwen3`, `gemma-3` on `mlx-lm`, `vllm` rejected)<br>`m4-max` (only `llama-3`, `deepseek`, `mistral` on `mlx-lm`) | Both `m3-max` and `m4-max` have **zero `llama.cpp`, `ollama`, `lmstudio`, or `vllm-metal` rows**. |
| **Missing from Taxonomy Entirely** | `m4-ultra`, `m5-ultra`<br>`a17-pro`, `a18`, `a18-pro`, `a19-pro` (iPhone/iPad Metal / MLC / llama.cpp)<br>`apple-ane` (Apple Neural Engine / CoreML) | • High-memory Mac Studio / Mac Pro tiers (`m4-ultra`, `m5-ultra`)<br>• Mobile iOS/iPadOS inference (`a17-pro`+ with 8–16 GB RAM) |
| **Missing `hw_aliases` for Apple** | `m1_pro` → `m1-pro`, `m1_max` → `m1-max`, `m1_ultra` → `m1-ultra`, `m2_pro` → `m2-pro`, `m2_max` → `m2-max`, `m2_ultra` → `m2-ultra`, `m3_pro` → `m3-pro`, `m3_max` → `m3-max`, `m3_ultra` → `m3-ultra`, `m4_pro` → `m4-pro`, `m4_max` → `m4-max`, `m5_pro` → `m5-pro`, `m5_max` → `m5-max`, `apple silicon` / `metal` / `macos` | Users and `CONTRACT.md` use underscore or space variants (`m4_pro`, `M4 Pro`) or device names (`Mac Studio`, `Mac Mini M4`). |

---

## 2. NVIDIA Hardware Gaps

| Category | Missing Slugs / Items | Real-World Cards & Relevance |
|---|---|---|
| **In Taxonomy, 0 Rows (8 archs)** | `sm_60`, `sm_61`<br>`sm_70`<br>`sm_87`<br>`sm_90a`<br>`sm_100a`, `sm_103`<br>`sm_121` | • `sm_60` / `sm_61`: **Pascal** (Tesla P100, Tesla P40 24GB, GTX 1080 Ti — huge budget local-LLM card)<br>• `sm_70`: **Volta** (Tesla V100 16/32GB)<br>• `sm_87`: **Jetson Orin** (AGX Orin 64GB, Orin NX/Nano — flagship edge LLM devkit)<br>• `sm_90a`: **H100 / H200 / GH200** Hopper accelerated instructions<br>• `sm_100a` / `sm_103`: **Blackwell B200 / B300 / GB200** datacenter variants<br>• `sm_121`: **DGX Spark (GB10 Grace Blackwell)** / next-gen Blackwell workstation |
| **In `nvidia.jsonl`, 0 Model Rows (3 archs)** | `sm_75` (Turing: T4, RTX 2080 Ti)<br>`sm_80` (Ampere: A100 40/80GB)<br>`sm_100` (Blackwell: B200) | Only have `vllm` / `llama.cpp` `*` rows; querying `a100` (`sm_80`) + `llama-3` or `qwen3` returns a miss! |
| **Missing from Taxonomy Entirely** | `sm_52` (Maxwell: Titan X / M40 24GB)<br>`sm_72` (Jetson Xavier)<br>`sm_110` (Jetson Thor) | Legacy 24GB hobbyist cards (`M40`) and robotics/edge modules (`Jetson Thor`). |
| **Missing `hw_aliases` for NVIDIA** | **Consumer cards:** `rtx3060`, `rtx3070`, `rtx3080ti`, `rtx4060`, `rtx4070`, `rtx4070ti`, `rtx4080`, `rtx5070`, `rtx5080`, `rtx2080ti`, `gtx1080ti`, `p40`, `p100`, `v100`<br>**Workstation/Datacenter:** `a10`, `a10g`, `a30`, `a40`, `a6000`, `rtx6000ada`, `l40`, `l40s`, `h200`, `gh200`, `gb200`, `dgx-spark`, `gb10`, `jetson-orin`<br>**Arch names:** `pascal` (`sm_61`), `volta` (`sm_70`), `turing` (`sm_75`) | Currently `hw_aliases` only maps `rtx3080`, `rtx3090`, `rtx4090`, `rtx5090`, `t4`, `l4`, `a100`, `h100`, `b200`. Mainstream cards like `rtx 4070` or `a6000` or `l40s` fail lookup. |

---

## 3. AMD Hardware Gaps

| Category | Missing Slugs / Items | Real-World Cards & Relevance |
|---|---|---|
| **In Taxonomy, 0 Rows (6 archs)** | `gfx900`, `gfx906`, `gfx908`<br>`gfx1032`, `gfx1034`<br>`gfx1102` | • `gfx900`: Vega 56 / Vega 64 / MI25<br>• `gfx906`: **Radeon VII (16GB HBM2) / MI50 / MI60 (32GB HBM2)** — very popular cheap 32GB HBM cards in r/LocalLLaMA<br>• `gfx908`: **Instinct MI100 (32GB HBM2)**<br>• `gfx1032`: RX 6600 / 6600 XT / 6650 XT (RDNA2)<br>• `gfx1034`: RX 6500 XT / 6400<br>• `gfx1102`: RX 7600 / 7600 XT (16GB) / 7700S (RDNA3) |
| **In `amd.jsonl`, 0 Model Rows (9 archs)** | `gfx90a` (MI210/MI250X)<br>`gfx950` (MI350/MI355X)<br>`gfx1030` (RX 6800/6900 XT)<br>`gfx1031` (RX 6700 XT)<br>`gfx1035` (Radeon 680M APU)<br>`gfx1101` (RX 7700/7800 XT)<br>`gfx1150` (Ryzen AI 300 / Radeon 890M)<br>`gfx1200`, `gfx1201` (RX 9070 XT / RDNA4) | Only `gfx1100` (RX 7900 XTX), `gfx1151` (Strix Halo), and `gfx942` (MI300X) have model-specific rows. Flagships like **MI250X (`gfx90a`)**, **RX 9070 XT (`gfx1201`)**, and **RX 6900 XT (`gfx1030`)** have 0 model rows. |
| **In Rows, Missing from Taxonomy (1 arch)** | `gfx1035` | Emitted in [amd.jsonl](file:///Users/windows/Model%20support%20for%20hardware%20site/data/rows/amd.jsonl) by `llama_cpp_backends.py` (RDNA2 Ryzen 6000/7035 APU iGPU, Radeon 680M) but not listed in `taxonomy.json`. |
| **Missing `hw_aliases` for AMD** | `rx7900xtx`, `rx7900xt`, `rx7900gre` → `gfx1100`<br>`rx7800xt`, `rx7700xt`, `w7800`, `w7900` → `gfx1101`/`gfx1100`<br>`rx7600xt` → `gfx1102`<br>`rx6900xt`, `rx6800xt`, `rx6800` → `gfx1030`<br>`rx6700xt` → `gfx1031`<br>`rx9070xt`, `rx9070` → `gfx1201`<br>`strix-halo`, `ryzen-ai-max` → `gfx1151`<br>`mi50`, `mi60`, `radeon-vii` → `gfx906`<br>`mi100` → `gfx908`<br>`rdna2` → `gfx1030`, `cdna2` → `gfx90a` | Users search by retail GPU name (`rx 7900 xtx`, `rx 6800 xt`, `strix halo`, `mi50`), not compiler target (`gfx1100`). |

---

## 4. Intel Hardware Gaps

| Category | Missing Slugs / Items | Real-World Cards & Relevance |
|---|---|---|
| **In Taxonomy, 0 Rows (7 archs)** | `arc-a750`, `arc-a730m`, `arc-a580`<br>`arc-b570`, `arc-b770`<br>`data-center-max-1100`<br>`flex-140` | • **Alchemist (`arc-a750`, `arc-a730m`, `arc-a580`):** Note that `SYCL.md` actually names `Arc A730M, Arc A750` in the verified table quote in [llama_cpp_backends.py](file:///Users/windows/Model%20support%20for%20hardware%20site/scrapers/sources/llama_cpp_backends.py#L236), but the scraper only emits `arc-a770`!<br>• **Battlemage (`arc-b570`, `arc-b770`):** 10GB/16GB+ desktop GPUs<br>• **Datacenter (`data-center-max-1100`, `flex-140`):** `SYCL.md` also names `Max 1550, 1100` on line 232, but only `data-center-max-1550` is emitted. |
| **In `intel.jsonl`, 0 Model Rows (9 archs)** | `arc-igpu-meteor-lake`, `arc-igpu-arrow-lake`, `arc-igpu-lunar-lake`, `arc-igpu-panther-lake`<br>`data-center-max-1550`, `flex-170`<br>`intel-igpu-11th-gen`, `intel-igpu-12th-gen`, `intel-npu` | Only `arc-a770` and `arc-b580` have specific model rows. |
| **In Rows, Missing from Taxonomy (4 archs)** | `arc-igpu-panther-lake`<br>`intel-igpu-11th-gen`, `intel-igpu-12th-gen`<br>`intel-npu` | Emitted in [intel.jsonl](file:///Users/windows/Model%20support%20for%20hardware%20site/data/rows/intel.jsonl) by `llama_cpp_backends.py`, but absent from `taxonomy.json` `hw_archs.intel`. |
| **Missing from Taxonomy Entirely** | `gaudi-2`, `gaudi-3` (Intel Gaudi AI accelerators — supported by vLLM)<br>`arc-pro-a60`, `arc-a380` | Intel Gaudi 2 / 3 are first-class vLLM backends. |

---

## 5. Qualcomm, ARM CPU, x86 CPU & Other Accelerator Gaps

| Vendor | In Taxonomy, 0 Rows | In Rows, Missing from Taxonomy | Missing from Taxonomy Entirely / 0 Model Combos |
|---|---|---|---|
| **Qualcomm** (`qualcomm`) | `snapdragon-x-plus`<br>`snapdragon-8cx-gen3` | `snapdragon-8-elite-gen5`<br>`snapdragon-7s-gen3`<br>`snapdragon-x2-elite`<br>`adreno-gpu` | • **0 model-specific rows across all 8 Qualcomm archs** (all 9 rows in `qualcomm.jsonl` are `*`).<br>• Missing `snapdragon-8-gen2` (Adreno 740). |
| **ARM CPU** (`arm-cpu`) | `aarch64-dotprod`<br>`aarch64-i8mm`<br>`rv64-spacemit-s390x` *(note: chimeric slug mixing RISC-V SpacemiT and IBM s390x!)* | `aarch64-bf16` | • **0 model-specific rows across all ARM CPU archs.**<br>• Missing `aarch64-sve` / `aarch64-sve2`, `aarch64-sme` (KleidiAI SME kernels), `grace-cpu` (NVIDIA Grace ARM), `raspberry-pi-5` (Cortex-A76).<br>• `rv64-spacemit-s390x` in `taxonomy.json` appears to be a typo concatenation of `rv64-spacemit` (RISC-V SpacemiT K1/M1) and `s390x`. |
| **x86 CPU** (`x86-cpu`) | `x86-64-avx512-vnni`<br>`x86-64-amx-int8`<br>`x86-64-sse42` | `x86-64-amd-zen2`<br>`x86-64-amd-zen3`<br>`x86-64-amd-zen4`<br>`x86-64-amd-zen5`<br>`generic` | • All 32 `hf_models` rows sit on `x86-cpu/generic` with `missing: ["model", "hw"]`.<br>• All real ISA/Zen architectures (`avx2`, `avx512`, `zen2`–`zen5`) have **0 model-specific rows**. |
| **Other** (`other`) | `generic` | `ascend-310p`, `ascend-910b`<br>`et-soc-1`<br>`ibm-z-s390x`, `ibm-z15`, `ibm-z16`, `ibm-z17`<br>`mtt-s80`, `mtt-s4000`, `mtt-s5000`<br>`virtgpu-generic` | • None of the 11 active `other` architectures are registered in `taxonomy.json` (`hw_archs.other` only has `["generic"]`).<br>• Missing Google `tpu-v5e` / `tpu-v6e` (supported by vLLM), AWS `inferentia2` / `trainium`, Tenstorrent `grayskull` / `wormhole`, RISC-V `rv64gcv`. |

---

## 6. Additional Emerging Hardware Worth Tracking

Beyond filling the taxonomy gaps above, these categories are increasingly prominent in local and self-hosted inference:

1. **AI Mini-PCs & Unified-Memory Boxes:**
   - **NVIDIA DGX Spark / Project DIGITS (`sm_121` / `gb10`):** 128 GB unified LPDDR5x Grace Blackwell superchip. (`sm_121` is in `taxonomy.json` with 0 rows and no `dgx-spark` / `gb10` alias).
   - **AMD Ryzen AI MAX+ 395 / 390 / 385 ("Strix Halo" `gfx1151` & "Krackan Point" `gfx1152`):** Up to 128 GB unified memory; `gfx1152` is not yet in `taxonomy.json`.
   - **Jetson AGX Thor (`sm_110`) & Jetson Orin Nano Super (`sm_87`):** Edge/robotics local LLM modules (`sm_87` has 0 rows; `sm_110` is not in taxonomy).
2. **Consumer Workstation & ProViz GPUs (High VRAM):**
   - **NVIDIA RTX PRO 6000 Blackwell (96 GB GDDR7, `sm_120`)**, **RTX 6000 Ada (48 GB, `sm_89`)**, **RTX 5000 Ada (32 GB)**, **RTX A6000 (48 GB, `sm_86`)**, **L40S (48 GB, `sm_89`)** — heavily used for 70B+ local inference, need `hw_aliases` and `hw_extra.vram_gb` variants.
   - **AMD Radeon PRO W7900 (48 GB, `gfx1100`) & W7800 (32 GB)** and **AI PRO R9700 (32 GB, `gfx1201`)**.
   - **Intel Arc Pro B60 (24 GB, Battlemage)** and **Arc Pro A60 (12 GB)**.
3. **Mobile & Handheld Gaming SoCs:**
   - **Apple A-Series:** `a17-pro`, `a18`, `a18-pro`, `a19-pro` (8–12+ GB RAM running `mlx-swift`, `llama.cpp`, and `mlc-llm` on iOS/iPadOS).
   - **MediaTek Dimensity (`dimensity-9300`, `dimensity-9400`) & Google Tensor (`tensor-g4`, `tensor-g5`):** Flagship Android NPUs/GPUs supported via `llama.cpp` OpenCL/Vulkan/KleidiAI and `mlc-llm`.
   - **AMD Handheld APUs:** Ryzen Z1 Extreme (`gfx1103`, ROG Ally / Legion Go) and Steam Deck (`gfx1033`) — `gfx1103` and `gfx1033` are common RDNA3/RDNA2 APU targets not in `taxonomy.json`.
4. **Dedicated NPUs & Edge PCIe Accelerators:**
   - **AMD Ryzen AI XDNA / XDNA2 NPU (`amd-xdna`, `amd-xdna2`):** Alongside Intel NPU (`intel-npu`) and Qualcomm Hexagon (`hexagon-npu`).
   - **Tenstorrent (`wormhole-n150`, `wormhole-n300`, `blackhole`)**, **Hailo-10H (M.2 GenAI NPU)**, **Axelera Metis**, **SiMa.ai**, and ** FuriosaAI RNGD**.
5. **Cloud/Datacenter Open-Weight Accelerators (Supported by vLLM / SGLang):**
   - **Google Cloud TPU (`tpu-v5e`, `tpu-v6e`)**
   - **Intel Gaudi (`gaudi-2`, `gaudi-3`)**
   - **AWS Neuron (`inferentia2`, `trainium1`, `trainium2`)**
   - **Meta MTIA / Groq LPU / Cerebras** (if tracking hosted open-weight engines, though `canirun` focuses on local/self-hosted runtimes).

---

## 7. How Users Can Add Their Own Hardware Today (and Where the Gaps Are)

`canirun` has **four paths** for users/agents to add combinations or request missing hardware—two live in-app paths (which create `untested` demand rows) and two GitHub contribution paths (which add verified rows or new taxonomy hardware):

### Path 1: In-App "+1 Want" Voting on Any Hardware Slug (`POST /api/want/{id}`)
- **How it works:** When a user types *any* hardware slug into the Lookup UI (even a brand-new `hw_arch` that does **not** exist in `taxonomy.json` yet, e.g. `apple/m4-ultra/qwen3/mlx-lm`) and gets a miss, they can click **`+1 want this Combo`** (or an agent can `POST /api/want/apple/m4-ultra/qwen3/mlx-lm`).
- **Does it allow new hardware?** **Yes!** Look at [api/store.py](file:///Users/windows/Model%20support%20for%20hardware%20site/api/store.py#L304-L343) and [pipeline/schema.py](file:///Users/windows/Model%20support%20for%20hardware%20site/pipeline/schema.py):
  - `hw_vendor` must be one of the 8 vendors (`nvidia`, `amd`, `intel`, `apple`, `qualcomm`, `arm-cpu`, `x86-cpu`, `other`), and `runtime` must be a valid runtime in `taxonomy.json`.
  - **However, `hw_arch` is NOT restricted to `taxonomy.json`!** Any lowercase slug matching `^[a-z0-9][a-z0-9_-]*$` (no dots) is accepted and materializes an `untested` row in `data/rows/<vendor>.jsonl` once it crosses the vote threshold (`CREATES_WANTED_AT = 3`, or immediately in the live `/api/untested` overlay).
- **UI caveat:** In [web/js/app.js](file:///Users/windows/Model%20support%20for%20hardware%20site/web/js/app.js), `idFor(q)` infers `hw_vendor` from known `taxonomy.hw_archs`, existing rows, or prefix rules (`sm_` → `nvidia`, `gfx` → `amd`, `arc-` → `intel`, `m1`–`m5` → `apple`, `snapdragon` → `qualcomm`, etc.), falling back to `other/<arch>` if unrecognized.

### Path 2: Automatic Miss Promotion (`POST /api/miss` / `GET /api/lookup`)
- **How it works:** When 3 distinct searchers (`CREATES_WANTED_AT = 3` in [api/store.py](file:///Users/windows/Model%20support%20for%20hardware%20site/api/store.py#L46)) search for a missing `hw × model × runtime` combination on the live server, `Store.log_miss()` triggers a background pipeline rebuild that automatically promotes the miss into an `untested` row in `data/rows/<vendor>.jsonl`.

### Path 3: 1-Click GitHub Issue Submission ("Submit Combo" Form)
- **How it works:** On any miss panel or combo card in the web UI ([web/js/render.js](file:///Users/windows/Model%20support%20for%20hardware%20site/web/js/render.js#L492-L545)), clicking **`I got this working — submit pointer`** or **`Submit evidence / report issue`** opens a pre-filled GitHub Issue using [.github/ISSUE_TEMPLATE/submit-combo.yml](file:///Users/windows/Model%20support%20for%20hardware%20site/.github/ISSUE_TEMPLATE/submit-combo.yml).
- **Does it allow new hardware?** The `hw_arch` field in `submit-combo.yml` is a free-text input, so users can type any new architecture slug plus a pointer URL and verbatim quote. However, **there is currently no automated GitHub Action to ingest approved issue forms into `data/rows/<vendor>.jsonl` or `data/taxonomy.json`**—a maintainer has to add the row manually.

### Path 4: Pull Request (`CONTRIBUTING.md`)
- **How it works:** Per [CONTRIBUTING.md](file:///Users/windows/Model%20support%20for%20hardware%20site/CONTRIBUTING.md), contributors can add a `hand` row to [scrapers/sources/curated_combos.py](file:///Users/windows/Model%20support%20for%20hardware%20site/scrapers/sources/curated_combos.py) or `data/rows/<vendor>.jsonl` and run `python3 pipeline/build.py --check`.
- **Gap in `CONTRIBUTING.md`:** `CONTRIBUTING.md` explains how to add a *combination row*, but does **not** explain how a contributor should register a new `hw_arch` or `hw_aliases` entry in `data/taxonomy.json` (or `data/taxonomy.extensions.json`) so that it shows up in the UI autocomplete dropdowns.

---

## Recommended Next Steps

1. **Sync `taxonomy.json` with existing scraped architectures:** Add the 26 orphan row architectures (`gfx1035`, `intel-npu`, `arc-igpu-panther-lake`, `x86-64-amd-zen2..5`, `ascend-910b`, `mtt-s4000`, etc.) to `taxonomy.json` and split the typo `rv64-spacemit-s390x`.
2. **Expand Apple Silicon coverage (`apple.jsonl`):**
   - Add `m4-ultra`, `m5-ultra`, and `a17-pro`/`a18-pro` to `taxonomy.json`, plus `hw_aliases` for all Apple M-series chips (`m1_pro`..`m5_max`, `mac studio`, `macbook pro`).
   - Add verified `solved` (and `untested` with `basis: "docs-claim"` or `"analogy"`) rows across `m1`–`m5` Pro/Max/Ultra tiers for `mlx-lm`, `llama.cpp`, `ollama`, and `vllm-metal`.
3. **Extract already-quoted Intel & NVIDIA hardware from existing docs:**
   - In `llama_cpp_backends.py`, emit `arc-a750`, `arc-a730m`, `data-center-max-1100`, and `arc-igpu-lunar-lake` / `arc-igpu-arrow-lake` from the `SYCL.md` lines already fetched and verified.
4. **Expand `hw_aliases` for consumer GPUs:** Map mainstream NVIDIA (`rtx 3060`, `rtx 4070`, `a6000`, `l40s`, `p40`, `dgx-spark`) and AMD (`rx 7900 xtx`, `rx 7800 xt`, `rx 6800 xt`, `mi50`, `strix halo`) names to their `sm_*` and `gfx*` targets.
5. **Improve the User Hardware Submission Flow:**
   - Document in `CONTRIBUTING.md` how to add new `hw_archs` and `hw_aliases` to `data/taxonomy.json`.
   - Optionally add a "Request / Add New Hardware" section or script (e.g., an issue-to-PR / CLI helper) so community-submitted `submit-combo.yml` issues can be validated and appended in one command.
