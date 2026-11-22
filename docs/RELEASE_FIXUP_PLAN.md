# Release Fixup Plan & Agent Spec — `solve.run` v1.0

**Goal:** Resolve all P0 data-credibility blockers, P1 repo/ops hygiene items, and corpus gaps before public release (r/LocalLLaMA, Hacker News, portfolio).

**Execution model:** **2 waves.**
- **Wave 1 (5 parallel agents):** Disjoint file write scopes. No two agents edit the same file.
- **Wave 2 (1 integrator agent):** Runs after Wave 1 completes—cleans poisoned stored rows, rebuilds the corpus, refreshes `web/snapshot.js`, and runs the full verification gate.

> **Invariant for all agents:** Read `CONTRACT.md` before editing. Do not change any key name, enum value, or id format in `CONTRACT.md`. Never fabricate a quote, URL, benchmark number, or hardware claim.

---

## Ownership Matrix (Wave 1 — Disjoint Write Scopes)

| Agent | Owns (writes allowed) | Read-only |
|---|---|---|
| **A1: `scraper-fixes`** | `scrapers/sources/llama_cpp_backends.py`, `scrapers/sources/gh_issues.py`, `scrapers/sources/gh_releases.py`, `scrapers/common.py` | `CONTRACT.md`, `data/taxonomy.json` |
| **A2: `pipeline-hygiene`** | `pipeline/normalize.py`, `pipeline/votes.py`, `pipeline/build.py`, `pipeline/tests/test_pipeline.py` | `CONTRACT.md`, `pipeline/schema.py` |
| **A3: `corpus-seed`** | `scrapers/sources/curated_combos.py`, `scrapers/run_all.py` (register source only) | `CONTRACT.md`, `data/taxonomy.json`, `scrapers/common.py` |
| **A4: `api-hardening`** | `api/server.py`, `api/store.py`, `api/tests/test_api.py` | `CONTRACT.md`, `pipeline/build.py` |
| **A5: `repo-release-docs`** | `README.md`, `LICENSE`, `CONTRIBUTING.md`, `api/DEPLOY.md`, `HANDOFF.md` (delete or move to `docs/archive/`) | everything else |

**Wait for Wave 2:** Nobody in Wave 1 edits `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl`, or `web/snapshot.js`.

---

## Wave 1 — Agent Specifications

### Agent A1 (`scraper-fixes`): Stop false-positive rejections & fix `llama.cpp` revision

**Problems to fix:**
1. **SYCL drop falsely marks H100 (`sm_90`) as `rejected` on `llama.cpp`:**
   - In `scrapers/sources/llama_cpp_backends.py` (lines 277–286), `SYCL.md` emits `nvidia/sm_90/*/llama_cpp` with `status="rejected"`.
   - **Fix:** Remove that emission (or emit it only if a `sycl`-specific runtime existed—do **not** mark `nvidia/sm_90/*/llama_cpp` rejected when CUDA supports `sm_90`). Keep `other/ibm-z16/*/llama_cpp` only if `z16` is genuinely unsupported by zDNN *and* clarify in `notes` that plain s390x CPU still works, or drop it if it contradicts `x86/s390x` CPU support.
2. **Narrow GitHub bug reports falsely mark major GPUs as `rejected` across all models (`*`):**
   - In `scrapers/sources/gh_issues.py` (lines 87–98, 158–171), any issue title containing `"bug"`, `"error"`, `"fail"`, `"crash"`, `"hang"`, or `"regression"` emits `status="rejected"` for `model_family="*"`.
   - This currently marks **RTX 5090 (`sm_120`), RX 7900 XTX (`gfx1100`), RX 6800 (`gfx1030`), MI300X (`gfx942`), Strix Halo (`gfx1151`), M3 Max (`mlx`), M1 (`ollama`), and Arc A770 (`llama.cpp`)** as `rejected`.
   - **Fix:**
     - Restrict `NEG` to explicit blanket-incompatibility verdicts only: `\b(not supported|unsupported|drop(?:ped|s)? support|remove[ds]? support|incompatible|does not support|no support for)\b`.
     - Do **not** treat ordinary bug reports (`bug`, `error`, `crash`, `hang`, `regression`, `slow`, `fail`) as `status="rejected"` for `model_family="*"`.
     - If an issue title explicitly names a taxonomy model family (e.g. `qwen3`, `deepseek`, `llama-3`) alongside a hardware token and a clear incompatibility verdict, emit it scoped to that `model_family` instead of `"*"`.
     - Ensure `scrapers/common.py` sends `Authorization: Bearer <GITHUB_TOKEN>` when `os.environ.get("GITHUB_TOKEN")` is set, so `gh_issues` does not hit unauthenticated 403 rate limits.
3. **`llama.cpp` pinned to legacy `v1.0.0` tag:**
   - In `scrapers/sources/gh_releases.py` (lines 50–57), `releases/latest` for `ggml-org/llama.cpp` returns `v1.0.0`.
   - **Fix:** For `ggml-org/llama.cpp`, scan `releases?per_page=10` and pick the newest `b\d+` tag (e.g., `b6400+`) instead of `v1.0.0`.

**Acceptance criteria (A1):**
- `python3 scrapers/run_all.py --offline --only llama_cpp_backends gh_issues gh_releases` succeeds with 0 rejects.
- `scrapers/out/llama_cpp_backends.jsonl` has **no** `rejected` row for `nvidia/sm_90/*/llama_cpp`.
- `scrapers/out/gh_issues.jsonl` has **zero** `rejected` rows whose evidence quote is an ordinary bug/eval/compile issue on a supported GPU.
- `scrapers/out/runtime_revs.json` shows a `b####` tag (not `v1.0.0`) for `ggml-org/llama.cpp` when run online.

---

### Agent A2 (`pipeline-hygiene`): Demo-vote isolation & upstream-doc merge precedence

**Problems to fix:**
1. **Demo votes leak permanently into `data/rows/*.jsonl`:**
   - Currently, `pipeline/build.py` (lines 220–231) withdraws demo-*created* rows on non-`--demo` builds, but leaves `demo:user...` entries in `want_requesters` and `want_votes` on pre-existing scraped rows (currently 9 rows in `data/combos.json` have fake demo votes even though `data/votes.json` is `{}`).
   - **Fix:** In `pipeline/votes.py` / `pipeline/build.py`, on any non-`--demo` build:
     - Strip all requesters starting with `"demo:"` from every row's `want_requesters`.
     - Recompute `want_votes` from real `data/votes.json` + real `data/misses.jsonl` (never preserving stale demo counts).
     - Reset `want_first` to `None` if `want_votes == 0` and `status != "wanted"`.
2. **Community issue reports overwrite `upstream-doc` `solved` rows during merge:**
   - In `pipeline/normalize.py` (`merge_sort_key`, lines 98–105), a `scraped` row from `gh_issues` (`status: "rejected"`) has the same `source_kind` rank as a `scraped` row from `llama_cpp_backends` or `vllm_install` (`status: "solved"`). Ties break by `base_score` / `reported_by`, allowing a single community issue to flip an officially supported card to `rejected`.
   - **Fix:** Add an evidence-authority tiebreaker inside `merge_sort_key` (after `source_kind` rank):
     - `upstream-doc` / `package-table` / `release` > `model-repo` > `issue` > `community`.
     - When merging an `upstream-doc` `solved` row with an `issue` `rejected` row on the same id, the `upstream-doc` row wins the base (`status: "solved"`), and the issue URL/quote is still preserved in `evidence` (and optionally noted) rather than flipping the card to `rejected`.
3. **Add regression tests in `pipeline/tests/test_pipeline.py`:**
   - `test_demo_votes_do_not_leak_onto_existing_rows_after_real_build`
   - `test_upstream_doc_solved_beats_community_issue_rejected_on_merge`

**Acceptance criteria (A2):**
- `python3 pipeline/tests/test_pipeline.py` passes 100% (including both new regression tests).
- Running `build(demo=True)` followed by `build(demo=False)` leaves **zero** `demo:` requesters and `want_votes == 0` on all unvoted rows.

---

### Agent A3 (`corpus-seed`): Curated mainstream `hardware × model × runtime` rows

**Problem to fix:**
The corpus currently has **0** complete `hardware × model × runtime` rows for NVIDIA, AMD, Apple Silicon, or Intel (only 6 Ascend/ET-SOC rows). Anyone trying the site on launch day gets a miss for every mainstream query.

**Task:**
Create `scrapers/sources/curated_combos.py` (registered in `scrapers/run_all.py`) emitting **25–40 verified `source_kind: "hand"` rows** covering the highest-traffic local inference combinations:

- **Target hardware (at least 1–3 rows each):**
  - NVIDIA: `sm_120` (RTX 5090), `sm_89` (RTX 4090), `sm_86` (RTX 3090), `sm_90` (H100)
  - AMD: `gfx1100` (RX 7900 XTX), `gfx1151` (Strix Halo / Ryzen AI MAX), `gfx942` (MI300X)
  - Apple: `m3-max`, `m4-max`
  - Intel: `arc-b580`, `arc-a770`
- **Target model families:** `qwen3`, `llama-3`, `deepseek`, `gemma-3`, `mistral`, `gpt-oss`
- **Target runtimes:** `llama.cpp`, `vllm`, `mlx-lm`, `ollama`
- **Mix of states:** Mostly `solved` (verified working guides, official recipes, vendor blog posts, or upstream docs/discussions), plus **3–5 genuine, verifiable `rejected` rows** (real architectural incompatibilities, e.g., FP8 hardware-native kernels unsupported on Ampere `sm_86` / RDNA3 `gfx1100`, or vLLM CUDA-only features on Apple Silicon) so the `rejected` state is legitimately demonstrated on real data.

**Strict anti-fabrication rules (non-negotiable):**
- Every row MUST fetch its `pointer` URL via `http` and verify its `evidence[].quote` with `common.verbatim()` (or be backed by a real, live, reachable upstream URL verified during the run—zero invented URLs or paraphrased quotes).
- Every row must pass `scrapers/validate_raw.py` and `pipeline/schema.validate()` with `missing: []`.
- Every row uses `source_kind: "hand"`, `created_by: "hand"`, `reported_by: "curated:v1"`.

**Acceptance criteria (A3):**
- `python3 scrapers/run_all.py --only curated_combos` exits 0 with 0 rejects and ≥25 rows.
- Every pointer URL returns HTTP 200 (verified by `pipeline/check_links.py`).
- All 4 major GPU/SoC vendors (NVIDIA, AMD, Apple, Intel) have ≥3 non-star `solved` rows.

---

### Agent A4 (`api-hardening`): Non-blocking rebuilds & test cleanup

**Problems to fix:**
1. **Synchronous `pipeline.build.build()` on HTTP write threads:**
   - In `api/server.py` (lines 457–463 and 543–549), crossing the miss/vote threshold calls `store_mod.try_pipeline_rebuild(self.store.data_dir)` synchronously inside `do_POST`. Under load or a larger corpus, this blocks HTTP responses and can run concurrent rebuilds.
   - **Fix:** Add a coalescing background rebuild scheduler on `Store` (`schedule_rebuild()`):
     - Uses a `threading.Lock` + single worker/coalescing flag (`_rebuild_running`, `_rebuild_pending`) so at most one rebuild runs at a time, and any triggers arriving mid-rebuild coalesce into one follow-up run.
     - Keep a `sync=True` option (or test hook) if existing tests assert immediate visibility after `POST /api/miss`, OR ensure `Store`'s in-memory overlay reflects votes/misses immediately (votes already do; make `lookup` reflect threshold-crossed misses immediately or wait only when `sync_rebuild=True` in tests).
     - Return `{"scheduled": True}` (or keep existing `pipeline_rebuild` key shape backwards-compatible with `test_api.py`).
2. **Fix `ResourceWarning: unclosed file` in `api/tests/test_api.py` line 380:**
   - Wrap `open(os.path.join(self.data, "votes.json"))` in a `with` context manager.

**Acceptance criteria (A4):**
- `python3 api/tests/test_api.py` passes with 0 failures and **0 `ResourceWarning`s**.
- Concurrent `POST /api/want` calls never run overlapping `pipeline.build.build()` executions.

---

### Agent A5 (`repo-release-docs`): External-ready README, license, and contribution path

**Tasks:**
1. **Add `LICENSE`:** MIT License for source code, with a short note that `data/` (`export.jsonl`, `combos.json`, `rows/*.jsonl`) is dedicated to the public domain under CC0-1.0 so anyone can mirror or consume the dataset freely.
2. **Rewrite `README.md` for external users:**
   - Remove all internal/private references (`00 My Notes/...`, `40 Reference/App Docs/Agent Builds/Loom/...`, `"O's ruling"`, `"O's standing rule"`, `"Decisions taken lands-on-the-lead"`).
   - Structure cleanly: **What it is** (2 sentences + the 4 states table) → **Quick start** (`serve.py`, `build.py`, `run_all.py`) → **API & Agent integration** (2-line curl + link to `/api/docs`) → **Data honesty model** (`scraped` vs `derived` vs `hand`, `*` hardware rows) → **Contributing** (link to `CONTRIBUTING.md`).
3. **Add `CONTRIBUTING.md`:**
   - Clear 1-page guide for humans to add a `solved` or `rejected` combination:
     - Option A: Open a GitHub Issue with hardware arch, model family, runtime, pointer URL, and quote.
     - Option B: Submit a PR adding a row to `scrapers/sources/curated_combos.py` (or `data/rows/<vendor>.jsonl`) and running `python3 pipeline/build.py --check`.
4. **Scrub internal notes from `api/DEPLOY.md` and retire `HANDOFF.md`:**
   - Remove `"O's standing rule"` / internal agent references from `api/DEPLOY.md`.
   - Remove `HANDOFF.md` from repo root (or move to `docs/archive/HANDOFF.md` if you want history kept, though deleting it from `main` is cleaner for a public repo—it stays in git history).

**Acceptance criteria (A5):**
- `grep -rn "00 My Notes\|O's ruling\|O's standing\|lands-on-the-lead\|Loom/blueprints" README.md api/DEPLOY.md CONTRIBUTING.md` returns **0 matches**.
- `LICENSE` and `CONTRIBUTING.md` exist at repo root.

---

## Wave 2 — Integrator Agent (`release-integrator`)

Run **only after** all Wave 1 agents finish and their changes are merged.

**Steps (in exact order):**
1. **Clean poisoned stored rows before rebuilding:**
   Because `pipeline/normalize.py` never deletes stored rows, the old false-positive `rejected` rows and `demo:user...` votes baked into `data/rows/*.jsonl` will persist unless cleared once:
   - Remove `data/rows/*.jsonl` (since 100% of current rows are reproducible from `scrapers/out/*.jsonl` + `curated_combos.py`, and `data/votes.json` is `{}`).
2. **Re-run scrapers & pipeline:**
   ```bash
   python3 scrapers/run_all.py          # set GITHUB_TOKEN in env if available
   python3 pipeline/build.py --check
   python3 pipeline/check_links.py
   node web/tools/inline-snapshot.mjs
   ```
3. **Run full test suite:**
   ```bash
   python3 pipeline/tests/test_pipeline.py
   python3 api/tests/test_api.py
   ```
4. **Run Release Gate Audit (must exit 0):**
   ```bash
   python3 -c "
   import json, re, sys
   c = json.load(open('data/combos.json'))
   rows = c['rows']
   errs = []

   # 1. Zero demo votes
   demo = [r['id'] for r in rows if any('demo:' in x for x in r.get('want_requesters', []))]
   if demo: errs.append(f'demo votes still present: {demo}')

   # 2. Zero false-positive blanket rejections on flagship supported GPUs
   bad_rej = [r['id'] for r in rows if r['status'] == 'rejected' and r['model_family'] == '*'
              and r['hw_arch'] in {'sm_86','sm_89','sm_90','sm_120','gfx1100','gfx1030','gfx942','gfx1151','m1','m3-max','arc-a770'}]
   if bad_rej: errs.append(f'false-positive * rejections: {bad_rej}')

   # 3. Real mainstream model x hw rows exist
   mainstream = [r for r in rows if r['model_family'] != '*' and r['hw_vendor'] in {'nvidia','amd','apple','intel'} and r['status'] == 'solved' and not r.get('missing')]
   if len(mainstream) < 20: errs.append(f'too few mainstream solved model x hw rows: {len(mainstream)}')

   # 4. No dead pointers
   dead = [r['id'] for r in rows if not r.get('pointer_alive', True)]
   if dead: errs.append(f'dead pointers: {dead}')

   # 5. snapshot.js version matches combos.json
   snap = open('web/snapshot.js').read()
   m = re.search(r'\"version\":\s*\"([^\"]+)\"', snap)
   if not m or m.group(1) != c.get('version'):
       errs.append(f'snapshot.js stale: {m.group(1) if m else None} != {c.get(\"version\")}')

   # 6. No llama.cpp v1.0.0 rev
   v1 = [r['id'] for r in rows if r['runtime'] == 'llama.cpp' and r.get('runtime_rev') == 'v1.0.0']
   if v1: errs.append(f'llama.cpp still pinned to v1.0.0 on {len(v1)} rows')

   if errs:
       print('RELEASE GATE FAILED:', *errs, sep='\n  - ')
       sys.exit(1)
   print(f'RELEASE GATE PASSED: {len(rows)} rows, {len(mainstream)} mainstream model x hw solved, version {c[\"version\"]}')
   "
   ```
5. **Commit cleanly** and verify `git status` is clean.
