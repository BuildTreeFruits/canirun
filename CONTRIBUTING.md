# Contributing to solve.run

Contributions of verified `solved` and `rejected` hardware × model × runtime combinations are welcome. Every row must follow the schema in `CONTRACT.md` and include at least one `evidence` entry with a real URL and verbatim quote.

## Option A: Open a GitHub Issue

If you don't want to edit code, open an issue with:

- **Hardware architecture** (`hw_vendor` + `hw_arch`, e.g., `nvidia` / `sm_86`, `apple` / `m4_pro`, `amd` / `gfx1100`)
- **Model family** (`model_family`, e.g., `qwen3`, `llama-3.1`, or `*` for hardware-only backend support)
- **Runtime** (`runtime` slug from `data/taxonomy.json`, e.g., `llama.cpp`, `vllm`, `mlx-lm`)
- **Status** (`solved` or `rejected`, plus a short `notes` explanation if `rejected`)
- **Pointer URL & quote** (a link to docs, a release, or an issue, plus the relevant quote)

## Option B: Submit a Pull Request

1. Add your row to `scrapers/sources/curated_combos.py` (or directly to `data/rows/<vendor>.jsonl` if adding a `hand` row).
   - Required fields include `id`, `status`, `source_kind` (`"hand"` for manual entries), `hw_vendor`, `hw_arch`, `model_family`, `runtime`, `as_of` (`YYYY-MM-DD`), `reported_by`, `pointer`, `pointer_alive`, `want_votes`, `want_first`, `want_requesters`, and `evidence` (`[{ "url": ..., "quote": ..., "kind": ... }]`).
   - If `status` is `"rejected"`, `notes` must be non-null explaining why it fails.
   - Canonical `id` format: `{hw_vendor}/{hw_arch}/{model_family}/{runtime}` lowercased, with `.` replaced by `_` (e.g., `nvidia/sm_86/qwen2_5/llama_cpp`).
2. Validate the dataset:
   ```bash
   python3 pipeline/build.py --check
   ```
3. Commit your changes and open a Pull Request.
