# Contributing to canirun

Contributions of `solved`, `untested` (proposed, unverified), and `rejected` hardware × model × runtime combinations—as well as configuration **variants**—are welcome. Every row must follow the schema in `CONTRACT.md` and include at least one `evidence` entry with a real URL and verbatim quote.

> **Maintainer response & merge path:** Reviews may take a week or more. Pull requests that pass CI validation (`python3 pipeline/build.py --check`) from regular contributors may be merged directly.

## Option A: Open a GitHub Issue

If you don't want to edit code, open an issue using the **Submit Combo** form (`.github/ISSUE_TEMPLATE/submit-combo.yml`) with:

- **Hardware architecture** (`hw_vendor` + `hw_arch`, e.g., `nvidia` / `sm_86`, `apple` / `m4_pro`, `amd` / `gfx1100`)
- **Model family** (`model_family`, e.g., `qwen3`, `llama-3.1`, or `*` for hardware-only backend support)
- **Runtime** (`runtime` slug from `data/taxonomy.json`, e.g., `llama.cpp`, `vllm`, `mlx-lm`)
- **Status** (`solved`, `untested`, or `rejected`)
  - If `untested`, include `basis` (`docs-claim`, `analogy`, `author-says`, or `mine`) and an optional `basis_note`.
  - If `rejected`, include a `notes` explanation of why it fails.
- **Variant knobs (optional)** — if this is a variant of an existing base combo, include `parent` and at least one distinguishing knob (`quant`, `context_length`, `offload`, `runtime_version`, `driver_version`, `flags`, `fits`).
- **Pointer URL & quote** (a link to docs, a release, or an issue, plus the verbatim quote)

## Option B: Submit a Pull Request

1. Add your row to `scrapers/sources/curated_combos.py` (or directly to `data/rows/<vendor>.jsonl` if adding a `hand` row).
   - Required fields include `id`, `status`, `source_kind` (`"hand"` for manual entries), `hw_vendor`, `hw_arch`, `model_family`, `runtime`, `as_of` (`YYYY-MM-DD`), `reported_by`, `pointer`, `pointer_alive`, `want_votes`, `want_first`, `want_requesters`, and `evidence` (`[{ "url": ..., "quote": ..., "kind": ... }]`).
   - If `status` is `"untested"`, set `basis` (`"docs-claim"`, `"analogy"`, `"author-says"`, or `"mine"`) and optionally `basis_note`.
   - If `status` is `"rejected"`, `notes` must be non-null explaining why it fails.
   - Base `id` format (4 segments): `{hw_vendor}/{hw_arch}/{model_family}/{runtime}` lowercased, with `.` replaced by `_` (e.g., `nvidia/sm_86/qwen2_5/llama_cpp`).
   - Variant `id` format (5 segments): `{parent_id}/@{variant_slug}` (e.g., `nvidia/sm_86/qwen3/llama_cpp/@q4km-ngl99-c8192`). Set `parent` to the base `id` and include at least one distinguishing knob (`quant`, `offload`, `context_length`, `runtime_version`, `driver_version`, `flags`, `fits`). See `CONTRACT.md` §2 for the deterministic slug order.
2. Validate the dataset:
   ```bash
   python3 pipeline/build.py --check
   ```
3. Commit your changes and open a Pull Request.

## Adding a New Hardware Architecture or Alias

1. **In the Lookup UI (no PR required):**
   - Users can immediately vote on any unlisted hardware slug using the **Want this** button.
   - Users who have a working setup can submit a pointer directly via the 1-click **"I got this working — submit pointer"** button, which pre-fills the GitHub issue form.
2. **In the repository (for contributors & maintainers):**
   - Register a new `hw_arch` under `hw_archs.<vendor>` and any search `hw_aliases` in `data/taxonomy.json`, or use the helper CLI:
     ```bash
     python3 scripts/ingest_combo.py --vendor apple --arch m4-ultra --hw-name "Apple M4 Ultra" --model qwen3 --runtime mlx-lm --status solved --quant mlx-4bit --pointer "https://huggingface.co/mlx-community/Qwen3-32B-4bit" --quote "from mlx_lm import load, generate" --notes "Qwen3-32B-4bit runs on Apple M4 Ultra via mlx-lm." --register-taxonomy
     ```
