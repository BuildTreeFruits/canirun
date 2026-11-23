# canirun

[![CI](https://github.com/BuildTreeFruits/canirun/actions/workflows/ci.yml/badge.svg)](https://github.com/BuildTreeFruits/canirun/actions/workflows/ci.yml)
[![Deploy GitHub Pages](https://github.com/BuildTreeFruits/canirun/actions/workflows/pages.yml/badge.svg)](https://github.com/BuildTreeFruits/canirun/actions/workflows/pages.yml)
[![License: MIT / CC0-1.0](https://img.shields.io/badge/License-MIT%20%2F%20CC0--1.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B%20(stdlib%20only)-3776AB.svg)](api/server.py)

A canonical index of **hardware × model × runtime** combinations for local LLM and generative AI inference. It answers whether a verified working path exists for a specific GPU/SoC, model family, and inference engine—or whether that combination is a recorded failure, an unverified proposal, or an unsearched gap.

---

## State Model

Every combination in the index falls into one of four states (three stored, one implicit):

| State | Meaning | Stored? | Required Evidence / Metadata |
|---|---|---|---|
| `solved` | A working path exists and is pointed to | **Yes** | Verifiable `pointer` URL, `as_of` date, and verbatim `evidence` quote |
| `untested` | **Proposed, unverified** — someone believes it works (`basis`) or requested it (`want_votes`) | **Yes** | `basis` (`docs-claim`, `analogy`, `author-says`, `mine`) and/or `want_votes` (surfaced separately) |
| `rejected` | Tested or documented as not working on this hardware | **Yes** | `notes` explaining why it fails + upstream `evidence` |
| `not-searched` | Nobody has claimed or logged anything yet | **No** | Absence of a row *is* the state (returned as a structured `miss`) |

---

## Corpus Coverage at a Glance

The dataset tracks **317 combinations** across **8 hardware vendor categories**, **16 runtimes**, **38 model families**, and **140+ hardware search aliases**:

| Vendor Category | Canonical Architectures (`hw_arch`) | Example Retail & Alias Queries (`hw_aliases`) |
|---|---|---|
| **NVIDIA** (`nvidia`) | `sm_52`, `sm_60`, `sm_61`, `sm_70`, `sm_75`, `sm_80`, `sm_86`, `sm_87`, `sm_89`, `sm_90`, `sm_90a`, `sm_100`, `sm_100a`, `sm_103`, `sm_110`, `sm_120`, `sm_121` | `rtx 5090`, `rtx 4090`, `rtx 3090`, `a6000`, `l40s`, `h100`, `b200`, `dgx-spark`, `gb10`, `jetson-orin`, `p40`, `t4` |
| **Apple Silicon** (`apple`) | `m1`..`m1-ultra`, `m2`..`m2-ultra`, `m3`..`m3-ultra`, `m4`..`m4-ultra`, `m5`..`m5-ultra`, `a17-pro`..`a19-pro` | `m4 max`, `m3 ultra`, `m4_pro`, `mac studio`, `macbook pro`, `mac mini m4`, `apple silicon`, `metal` |
| **AMD** (`amd`) | `gfx900`, `gfx906`, `gfx908`, `gfx90a`, `gfx942`, `gfx950`, `gfx1030`..`gfx1035`, `gfx1100`..`gfx1103`, `gfx1150`..`gfx1152`, `gfx1200`, `gfx1201` | `rx 7900 xtx`, `rx 9070 xt`, `rx 6800 xt`, `strix halo`, `ryzen ai max`, `mi300x`, `mi250x`, `mi50`, `rdna3`, `cdna3` |
| **Intel** (`intel`) | `arc-a770`, `arc-a750`, `arc-a730m`, `arc-b580`, `arc-b570`, `arc-igpu-lunar-lake`, `arc-igpu-arrow-lake`, `arc-igpu-meteor-lake`, `arc-igpu-panther-lake`, `data-center-max-1550`, `data-center-max-1100`, `flex-170`, `intel-npu`, `gaudi-2`, `gaudi-3` | `arc b580`, `arc a770`, `max 1550`, `pvc`, `lunar-lake`, `arrow-lake` |
| **Qualcomm** (`qualcomm`) | `snapdragon-x-elite`, `snapdragon-x2-elite`, `snapdragon-8-elite`, `snapdragon-8-gen3`, `hexagon-npu`, `adreno-gpu` | `snapdragon-x-elite`, `hexagon-npu` |
| **x86 CPU** (`x86-cpu`) | `x86-64-avx2`, `x86-64-avx512`, `x86-64-amx-int8`, `x86-64-amd-zen2`..`zen5` | `avx2`, `avx512`, `amx`, `zen5`, `zen4`, `zen3` |
| **ARM / RISC-V CPU** (`arm-cpu`) | `aarch64-neon`, `aarch64-bf16`, `aarch64-dotprod`, `aarch64-i8mm`, `aarch64-sve2`, `aarch64-sme`, `arm64-android`, `rv64-spacemit`, `grace-cpu` | `aarch64-neon`, `arm64-android` |
| **Other Accelerators** (`other`) | `ascend-910b`, `ascend-310p`, `mtt-s4000`, `mtt-s80`, `et-soc-1`, `ibm-z17`, `ibm-z16`, `ibm-z15`, `ibm-z-s390x`, `virtgpu-generic`, `tpu-v5e`, `tpu-v6e`, `tenstorrent-wormhole` | `ascend-910b`, `mtt-s4000`, `ibm-z17` |

- **Runtimes (`data/taxonomy.json`):** `llama.cpp`, `vllm`, `mlx-lm`, `mlx`, `vllm-metal`, `ollama`, `sglang`, `exllamav2`, `exllamav3`, `lmstudio`, `mlc-llm`, `mllama`, `bitnet.cpp`, `vllm-xpu-kernels`.
- **Model Families:** `qwen3`, `qwen3-vl`, `qwen2.5`, `llama-3` (`llama-3.1`/`3.2`/`3.3`), `llama-4`, `deepseek` (`deepseek-v3`/`r1`), `gemma-3`, `gemma-4`, `mistral`, `mixtral`, `phi` (`phi-3`/`phi-4`), `gpt-oss`, `glm`, `kimi`, `granite`, `nemotron`, `minimax`, `olmo`, `smollm`, `whisper`, `stable-diffusion`, `flux`, `wan`, and more.

---

## Data Honesty Model

Upstream documentation rarely publishes a complete `hardware × model × runtime` matrix; instead, projects publish backend build guides, wheel tables, and model cards. To prevent synthesized joins or unverified guesses from masquerading as confirmed facts, every row is governed by [CONTRACT.md](CONTRACT.md):

1. **Provenance (`source_kind`) & Missing Dimensions (`missing`):**
   - **`scraped`** — Extracted directly from an upstream source with a verbatim-verified quote. Either a complete triple (`missing: []`) or an explicit hardware-level backend claim (`model_family: "*"`, `missing: ["model"]`).
   - **`derived`** — A synthesized join across sources. Always declares what it lacks in `missing` (e.g. `["model"]` or `["model", "hw"]`) and is clearly flagged in both the UI and API.
   - **`hand`** — Curated and verified by a contributor with a live `pointer` URL and verbatim quote.
   - **`author-claim`** — Reported directly by an upstream runtime or model author.
2. **Wildcard (`*`) Hardware Rows Are Context, Never Model Answers:**
   - When a source only states that a runtime backend supports an architecture (regardless of model), `model_family` is `"*"` and `missing` contains `"model"`.
   - In model-specific queries, `*` rows are returned exclusively under `context` (never in `rows`), and a query that only matches `*` rows returns `miss.is_miss: true` (`reason: "partial-context"`).
3. **`untested` Rows Separate Belief (`basis`) from Demand (`want_votes`):**
   - `untested` rows are always labeled **"proposed, unverified"** in API hints and UI cards.
   - `basis` (`docs-claim`, `analogy`, `author-says`, `mine`) records *why* a contributor believes a combo works; `want_votes` records *how many* users or agents want it verified.
4. **Configuration Variants (5-Segment IDs):**
   - Base combinations use a 4-segment canonical ID: `{hw_vendor}/{hw_arch}/{model_family}/{runtime}` (lowercased, with `.` replaced by `_`, e.g. `nvidia/sm_86/qwen3/llama_cpp`).
   - Specific configurations hang off a base row via `parent` with a deterministic 5-segment ID (`{parent_id}/@{variant_slug}`, e.g. `nvidia/sm_86/qwen3/llama_cpp/@q4km-ngl99-c8192`) derived from distinguishing knobs: `quant`, `offload`, `context_length`, `runtime_version`, `driver_version`, `flags`, and `fits` (`writing`, `coding`, `tools`, `long-context`, `multimodal`, `speed`).

---

## Quick Start

The entire stack uses **Python 3.11+ standard library only** (zero `pip` dependencies) and a **zero-build vanilla JS frontend** that also works offline directly over `file://`.

```bash
# Start the local web UI + live HTTP API at http://127.0.0.1:8787 (API docs at /api/docs)
python3 scripts/serve.py

# Rebuild data/combos.json, data/export.jsonl, and data/rows/*.jsonl (and verify determinism)
python3 pipeline/build.py --check

# Refresh the offline static snapshot (web/snapshot.js) from data/combos.json + data/taxonomy.json
node web/tools/inline-snapshot.mjs

# Re-run upstream scrapers (replay on-disk cache offline, or omit --offline for live 1 req/s fetch)
python3 scrapers/run_all.py --offline
```

**Static / Offline Mode:** Open `web/index.html` directly in a browser (or host the static tree on GitHub Pages). Without a running Python server, the UI automatically falls back to `data/combos.json` / `web/snapshot.js` with full client-side alias resolution and variant grouping.

### Running Tests

```bash
python3 pipeline/tests/test_pipeline.py   # Schema invariants, normalizer merge precedence, votes, variants
python3 api/tests/test_api.py             # HTTP endpoints, alias parity, ETag/304, rate limiting, votes/misses
node --test web/tests/smoke.mjs           # Frontend snapshot loading, alias lookup parity, UI rendering
```

---

## HTTP API & AI Agent Integration

Query combinations, log misses, or upvote demand over HTTP:

```bash
# Lookup by canonical arch or retail alias (e.g. "rtx 4090" -> sm_89, "qwen-3" -> qwen3)
curl -s "http://127.0.0.1:8787/api/lookup?hw=rtx+4090&model=qwen3"

# Browse proposed/unverified and community-wanted combinations
curl -s "http://127.0.0.1:8787/api/untested"

# Concise plain-text guide for LLMs and coding agents
curl -s "http://127.0.0.1:8787/llms.txt"

# Full JSONL dataset export (supports ETag / If-None-Match 304 caching)
curl -s "http://127.0.0.1:8787/api/export.jsonl"

# Upvote demand for a combination (4-segment base ID or 5-segment variant ID)
curl -s -X POST "http://127.0.0.1:8787/api/want/nvidia/sm_86/qwen3/llama_cpp" \
  -H "X-Voter: agent:my-tool"
```

See [api/AGENT.md](api/AGENT.md) for the paste-ready agent system prompt and tool description, [web/llms.txt](web/llms.txt) for the compact agent index, or visit `/api/docs` and `/api/openapi.json` when running `scripts/serve.py`.

---

## Repository Layout

```text
canirun/
├── web/                  # Zero-build static frontend (works on GitHub Pages, local server, or file://)
│   ├── index.html        # Single-page Lookup, Browse, Untested, and API reference UI
│   ├── js/               # Classic IIFE modules (lookup.js, render.js, app.js, api.js, format.js)
│   ├── css/app.css       # Light/dark responsive stylesheet
│   ├── llms.txt          # Plain-text index and epistemic rules for AI agents
│   └── tests/smoke.mjs   # Node.js frontend & API/JS lookup parity test suite
├── api/                  # Stdlib-only Python HTTP API service
│   ├── server.py         # ThreadingHTTPServer (/api/lookup, /api/untested, /api/want, /api/miss, etc.)
│   ├── store.py          # In-memory dataset index, alias resolution, atomic vote/miss persistence
│   ├── openapi.py        # OpenAPI 3.1 schema generator (/api/openapi.json)
│   ├── docs.py           # Human-readable API documentation renderer (/api/docs)
│   ├── AGENT.md          # Paste-ready system prompt & MCP tool shim for coding agents
│   └── DEPLOY.md         # Single-VPS deployment guide (systemd + Caddy + hourly vote backups)
├── pipeline/             # Deterministic dataset build & validation pipeline
│   ├── schema.py         # Row canonicalization, 11 contract invariants, variant slug derivation
│   ├── normalize.py      # Deduplication and authority-ranked merge across scraper sources
│   ├── join.py           # Cross-source model × hardware derived join
│   ├── votes.py          # Vote application and miss-threshold promotion
│   ├── check_links.py    # Pointer URL liveness checker
│   └── build.py          # Full build orchestrator (python3 pipeline/build.py --check)
├── scrapers/             # Upstream documentation, package, issue, and release scrapers
│   ├── sources/          # 7 source modules (llama.cpp, vLLM, Apple/MLX, Ollama, HF, GitHub, curated)
│   ├── common.py         # Rate-limited HTTP client, ETag cache, verbatim quote verifier
│   └── README.md         # Scraper architecture, anti-fabrication rules, and source breakdown
├── data/                 # Public-domain (CC0-1.0) dataset
│   ├── taxonomy.json     # Canonical vendors, architectures, search aliases, models, and runtimes
│   ├── rows/*.jsonl      # Canonical per-vendor combination rows
│   ├── combos.json       # Bundled JSON export consumed by the web UI and API
│   └── export.jsonl      # Single-file JSONL mirror export
├── scripts/
│   ├── serve.py          # Local dev server entrypoint
│   └── ingest_combo.py   # Validated CLI helper to add a combo or register new hardware
├── CONTRACT.md           # Frozen v1 data schema, ID rules, invariants, and API payload specification
├── CONTRIBUTING.md       # How to submit combinations, variants, or new hardware via Issue or PR
└── LICENSE               # MIT License (code) + CC0-1.0 Public Domain Dedication (data/)
```

---

## Contributing

Contributions of `solved`, `untested` (with `basis`), and `rejected` combinations—as well as configuration **variants** and new hardware aliases—are welcome:

- **No code required:** Open a pre-filled [Submit Combo issue](../../issues/new?template=submit-combo.yml) (or click **"I got this working — submit pointer"** directly inside the web UI).
- **Via Pull Request:** Add a row using `python3 scripts/ingest_combo.py` or in `scrapers/sources/curated_combos.py`, validate with `python3 pipeline/build.py --check`, and open a PR. See [CONTRIBUTING.md](CONTRIBUTING.md) for full details.

## License

- **Code (`api/`, `pipeline/`, `scrapers/`, `scripts/`, `web/`):** [MIT License](LICENSE)
- **Dataset (`data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl`):** [CC0 1.0 Universal (Public Domain)](LICENSE)
