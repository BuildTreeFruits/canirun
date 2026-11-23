# Master Fan-Out Goal Sheet — `canirun` Pre-Launch Completeness, Bug Fixes, Variants & `untested` State

> **Purpose:** Single authoritative execution spec for `/goal` with parallel Hydrogen agents. Every requirement from all unintegrated plans is consolidated, reconciled, and partitioned into **disjoint file write scopes** so Wave 1 agents can run 100% in parallel with zero merge conflicts, followed by a single Wave 2 Integrator agent.

---

## 0. Plan Inventory & Integration Status

| Source Document | Status | Disposition in This Sheet |
|---|---|---|
| `docs/RELEASE_FIXUP_PLAN.md` | **Landed** (`590bfe5`) | Already complete. Do **not** redo. |
| `docs/POST_RELEASE_PLAN.md` | **Wave 1 Landed** (`3a00235`); Wave 2 is VPS deploy/launch | Wave 1 complete. Wave 2 (VPS deploy + HN/Reddit launch) is **out of scope** (post-code ops). |
| `~/.gemini/antigravity-cli/brain/51cd75d2-e4b2-418e-83e6-c7cf8ee3b833/implementation_plan.md` | **Unintegrated** | **Fully integrated** into Waves 1–2 (Phases 1 & 2; Phase 3 uses Option A: honest `Untested (0)` on Day 0). |
| `docs/DESIGN_SPEC.md` (Hermes design spec, 2026-11-22) | **Unintegrated** (decided, not built) | **All "before the move" + schema/API/export/UI-grouping items integrated** (§1 D1–D8, D16–D17; §2.1–§2.5; §4). Deferred v2 items (§4 bottom & §3 open items) are **explicitly fenced out** below. |

---

## 1. Frozen Cross-Agent Contract & Conflict Reconciliations

**Every agent MUST read this section before editing.** Because `implementation_plan.md` was written against the legacy 4-state model (`wanted`) while `docs/DESIGN_SPEC.md` authoritatively merges `wanted` into `untested` and introduces variants, the following decisions are **frozen** for all agents in this run:

### 1.1 State Model (`wanted` → `untested`)
- **Stored states (`STATUSES`):** `("solved", "untested", "rejected")` (3 stored states).
- **Implicit unstored state:** `not-searched` (absence of a row *is* the state; never stored; Invariant 1 unchanged).
- **`untested` fields:**
  - `basis`: enum `("docs-claim", "analogy", "author-says", "mine")` or `None`.
    - **Required** (non-null, in enum) for all `untested` rows where `created_by not in ("vote", "miss")`.
    - **Nullable (`None`)** for `untested` rows created purely by demand (`created_by in ("vote", "miss")` — votes/misses record demand without a belief claim yet; per `DESIGN_SPEC.md` D5 & §2.2).
  - `basis_note`: `str | None` (optional free-text explanation of why the filer believes it works).
  - `want_votes`: `int >= 0` (demand count; `0` is valid on an `untested` row).
  - `want_first`: `YYYY-MM-DD | None` — **required only when `want_votes >= 1`** (nullable when `want_votes == 0`).
  - `want_requesters`: `list[str]` (capped at 10 for display; `want_votes` is authoritative).
- **Vote-flip inference (`pipeline/schema.py` `resolves_no_claim`):**
  - Per `DESIGN_SPEC.md` §2.1: an absence-claim rejection (`status == "rejected"`, no pointer) has no belief attached and must **not** silently flip to `untested` with `basis: "mine"`.
  - Flip a `rejected` row on votes to `untested` (`basis: "docs-claim"`) **only** if `resolves_no_claim` is true **and** the row carries a non-null `pointer`; otherwise leave `status: "rejected"` (votes still attach to `want_votes` without changing `status`).
- **Epistemic rule (D8 — Highest Severity):**
  - `api/store.py::_hint()`, `web/js/lookup.js::missHint()`, and the API/UI row payloads MUST explicitly state **"proposed, unverified"** for `untested` rows and MUST surface `basis` / `basis_note` **separately** from `want_votes`. Never present an `untested` row as a verified fact.
  - `miss.reason` enum becomes: `no-claim | untested-only | rejected-only | partial-context | no-match`.
  - In `miss` payload:
    - Keep `known_wanted` (bool) and `wanted_votes` (int) for backwards compatibility with existing clients, **and** add `known_untested` (bool), `untested_basis` (`list[str]` of distinct non-null bases on matching `untested` rows, sorted).
  - Keep `GET /api/wanted` route working (returning `untested` rows + any row with `want_votes > 0`, sorted by `want_votes desc, want_first asc`) and also expose `GET /api/untested` as an alias to the same handler. Keep `combos.json` `"wanted"` key populated with the same demand list for backwards compatibility.

### 1.2 Variants Schema & Deterministic Variant ID (`DESIGN_SPEC.md` D1–D4, D7)
- **Storage:** Variants live in the **same** `data/rows/<vendor>.jsonl` file as base rows (`parent: null` for base rows; `parent: "<parent_id>"` for variants).
- **Variant knob fields (all optional / nullable, default `None`):**
  | Field | Type | Example | Rule |
  |---|---|---|---|
  | `parent` | `str \| None` | `"nvidia/sm_86/qwen3/llama_cpp"` | If non-null, must resolve to an existing row `id` in the dataset (post-join check in `pipeline/build.py`). |
  | `quant` | `str \| None` | `"Q4_K_M"` | Already exists on base row; also acts as a variant knob when `parent` is non-null. |
  | `context_length` | `int \| None` | `8192` | Positive integer (`> 0`) or `None`. |
  | `offload` | `str \| None` | `"ngl=99"` | Free string or `None`. |
  | `runtime_version` | `str \| None` | `"b4700"` | String (cannot be in `BANNED_RUNTIME_REVS`) or `None`. |
  | `driver_version` | `str \| None` | `"cuda-12.4"` | String or `None`. |
  | `flags` | `str \| None` | `"--flash-attn"` | Free string or `None`. |
  | `fits` | `enum \| None` | `"coding"` | Fixed enum: `("writing", "coding", "tools", "long-context", "multimodal", "speed")` or `None`. |
- **At-least-one-knob invariant:** If `parent` is non-null, at least one of `(quant, context_length, offload, runtime_version, driver_version, flags, fits)` MUST be non-null/non-empty. Otherwise validation fails.
- **Deterministic Variant Slug & Canonical ID:**
  - Base row ID (4 segments, unchanged `CONTRACT.md` §2):
    `{hw_vendor}/{hw_arch}/{model_family_id}/{runtime_id}` (lowercase, `.` → `_`, `-` and `_` preserved).
  - Variant row ID (5 segments):
    `{parent_id}/@{variant_slug}`
  - **Deterministic `variant_slug` derivation** (fixed knob order, omitting `None`/empty knobs, joining present parts with `-`):
    1. `quant`: lowercase, strip `_` and non-`[a-z0-9]`, e.g. `Q4_K_M` → `q4km`
    2. `offload`: lowercase, strip `=` and spaces, keep `[a-z0-9]`, e.g. `ngl=99` → `ngl99`
    3. `context_length`: `c{int}`, e.g. `8192` → `c8192`
    4. `runtime_version`: `rv-{slug}`, where `{slug}` is lowercase `[a-z0-9]` with `.` → `_`
    5. `driver_version`: `drv-{slug}`, lowercase `[a-z0-9-]` with `.` → `_`
    6. `flags`: `f-{slug}`, lowercase tokens joined by `-` (leading `--` stripped, non-`[a-z0-9]` collapsed to `-`)
    7. `fits`: `fit-{fits}` (exact enum value)
    - Example: `quant="Q4_K_M"`, `offload="ngl=99"`, `context_length=8192` → `@q4km-ngl99-c8192`, producing `nvidia/sm_86/qwen3/llama_cpp/@q4km-ngl99-c8192` (exact match to `DESIGN_SPEC.md` D1!).
    - Variant slug regex: `^@[a-z0-9][a-z0-9_-]*$` (no dots allowed, consistent with `CONTRACT.md` §2).
- **`untested` propagation (D7):**
  - If a variant's `parent` row has `status == "untested"` and the variant is not explicitly `solved` or `rejected` with its own pointer/notes, the variant inherits `untested`.
  - Even if stored as `status: "untested"`, both API and UI detect when `parent.status == "untested"` and flag the variant as a **double-wish** (untested variant under an untested parent — must not read as a lead).

### 1.3 Alias Normalization Parity (`api/store.py` ↔ `web/js/lookup.js`)
- **Single normalization rule (`normToken` / `norm_token`):**
  `trim` → `lowercase` → replace `[._\s/]+` with `-` → collapse multiple `-` to single `-` → strip leading/trailing `-`.
- **Hardware aliases (`taxonomy.hw_aliases`):**
  - Build a lookup map `normToken(alias) -> normToken(canonical_arch)` (also keep raw canonical arch for UI display, e.g. `rtx4090` and `rtx 4090` → `sm_89`).
  - Also map space-collapsed forms (e.g. `normToken("rtx 4090")` is `"rtx-4090"`, while `taxonomy.json` has `"rtx4090": "sm_89"` — **CRITICAL:** strip hyphens/spaces in a secondary compact key `re.sub(r'[^a-z0-9]', '', s.lower())` so BOTH `"rtx4090"` AND `"rtx 4090"` resolve to `"sm_89"`, and `"arc b580"` AND `"arc-b580"` AND `"arcb580"` resolve to `"arc-b580"`!).
  - When matching `hw`: resolve incoming query `hw` through the alias map (exact `normToken` first, then compact alnum key). If resolved to a canonical `arch`, match rows against EITHER the original `hw` token OR the resolved canonical `arch`.
- **Model aliases (`taxonomy.models[].aliases`):**
  - Build a lookup map from each `alias` (both `normToken(alias)` and compact alnum key) → `model.family`.
  - When matching `model`: resolve incoming query `model` through the model alias map. Match rows against EITHER the original `model` token OR the resolved canonical `family`.
  - Examples that MUST resolve identically in Python and JS:
    - `hw=rtx4090` or `hw=rtx 4090` → `sm_89`
    - `hw=rtx3090` or `hw=ampere` → `sm_86`
    - `hw=rdna3` → `gfx1100`
    - `hw=mi300x` or `hw=cdna3` → `gfx942`
    - `hw=arc b580` → `arc-b580`
    - `model=llama3` or `model=llama-3.1` → `llama-3`
    - `model=qwen-3` → `qwen3`
    - `model=deepseek-r1` → `deepseek`
    - `model=phi-4` → `phi`

### 1.4 Guardrails (Non-Negotiable)
- **Zero-build / `file://` compatibility:** All `web/js/*.js` files MUST remain plain classic IIFE scripts (`(function (SR) { ... })(window.__SR = window.__SR || {});`). No ES `import`/`export` syntax in `web/js/*.js`.
- **Anti-fabrication:** Never fabricate URLs, quotes, or hardware claims.
- **No `data/rows/*.jsonl` edits in Wave 1:** Only Wave 2 runs `pipeline/build.py` and `node web/tools/inline-snapshot.mjs`.

### 1.5 Explicitly Out of Scope (Deferred to v2 — DO NOT BUILD)
Per `docs/DESIGN_SPEC.md` §3–§4, `implementation_plan.md` Phase 3 Option A, and `docs/POST_RELEASE_PLAN.md` Wave 2:
- Comment store (`data/comments.jsonl`), comment API endpoints, comment promotion path, and forum UI.
- Three-button contribution form (D10).
- `fits` query/filter UI controls (schema & payload support IS in scope; dedicated UI filter bar is v2).
- `not-searched` human guidance page ("here are three places to check").
- Confirm tallies / variant-to-parent status rollup (`DESIGN_SPEC.md` §3 #1–#2).
- Seeding fake or speculative `wanted`/`untested` rows on Day 0 (`implementation_plan.md` Phase 3 Option A: keep `Untested (0)` honest with a dedicated empty-state CTA).
- VPS deployment, Caddy/systemd rollout, and public launch posts.

---

## 2. Fan-Out Ownership Matrix (Disjoint Write Scopes)

### Wave 1 — 5 Parallel Agents (Run Simultaneously)

| Agent ID | Role | Allowed Write Scope (Exclusive) | Read-Only References |
|---|---|---|---|
| **W1-A** | `pipeline-schema-variants` | `pipeline/schema.py`, `pipeline/normalize.py`, `pipeline/votes.py`, `pipeline/build.py`, `pipeline/export.py`, `pipeline/tests/test_pipeline.py` | `CONTRACT.md`, `docs/DESIGN_SPEC.md`, `data/taxonomy.json` |
| **W1-B** | `api-aliases-untested` | `api/store.py`, `api/views.py`, `api/server.py`, `api/openapi.py`, `api/docs.py`, `api/tests/test_api.py`, `api/tests/make_fixtures.py`, `api/tests/fixtures/**` | `CONTRACT.md`, `docs/DESIGN_SPEC.md`, `data/taxonomy.json`, `pipeline/schema.py` |
| **W1-C** | `web-lookup-and-snapshot` | `web/js/lookup.js`, `web/tools/inline-snapshot.mjs`, `web/llms.txt` *(new)*, `web/fixtures/sample-combos.json` | `CONTRACT.md`, `docs/DESIGN_SPEC.md`, `data/taxonomy.json`, `api/store.py` |
| **W1-D** | `web-ui-fixes-and-ux` | `web/index.html`, `web/js/app.js`, `web/js/render.js`, `web/js/format.js`, `web/css/app.css` | `CONTRACT.md`, `docs/DESIGN_SPEC.md`, `web/js/lookup.js`, `data/taxonomy.json` |
| **W1-E** | `docs-contract-templates` | `CONTRACT.md`, `CONTRIBUTING.md`, `README.md`, `api/AGENT.md`, `.github/ISSUE_TEMPLATE/submit-combo.yml` *(new)* | `docs/DESIGN_SPEC.md`, `data/taxonomy.json` |

> **Rule:** No Wave 1 agent may edit files outside its Allowed Write Scope. No Wave 1 agent edits `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl`, `web/snapshot.js`, or `web/tests/smoke.mjs`.

### Wave 2 — 1 Integrator Agent (Run ONLY After All 5 Wave 1 Agents Finish)

| Agent ID | Role | Allowed Write Scope |
|---|---|---|
| **W2-INT** | `integrator-verify` | `web/tests/smoke.mjs`, `web/snapshot.js` *(generated)*, `data/combos.json` & `data/export.jsonl` *(via `pipeline/build.py`)*, plus minimal glue fixes if any cross-agent interface mismatch surfaces during testing. |

---

## 3. Detailed Wave 1 Agent Specifications

---

### Agent W1-A: `pipeline-schema-variants`

**Write Scope:** `pipeline/schema.py`, `pipeline/normalize.py`, `pipeline/votes.py`, `pipeline/build.py`, `pipeline/export.py`, `pipeline/tests/test_pipeline.py`

#### Requirements

1. **State & Enum updates in `pipeline/schema.py`:**
   - Line 33: Update `STATUSES = ("solved", "untested", "rejected")`.
   - Add constants:
     - `BASIS_VALUES = ("docs-claim", "analogy", "author-says", "mine")`
     - `FITS_VALUES = ("writing", "coding", "tools", "long-context", "multimodal", "speed")`
     - `VARIANT_KNOBS = ("quant", "context_length", "offload", "runtime_version", "driver_version", "flags", "fits")`
     - `VARIANT_SLUG_RE = re.compile(r"^@[a-z0-9][a-z0-9_-]*$")`
   - Export all new constants and helpers in `__all__`.

2. **Variant ID & Slug derivation in `pipeline/schema.py`:**
   - Implement `derive_variant_slug(row: Mapping[str, Any]) -> Optional[str]` following §1.2 exact knob order and formatting (`quant`, `offload`, `context_length`, `runtime_version`, `driver_version`, `flags`, `fits`). Returns `None` if all knobs are null/empty.
   - Update `derive_id(hw_vendor, hw_arch, model_family, runtime, *, variant_slug=None)` (or add `derive_variant_id(parent_id, variant_slug) -> str` returning `f"{parent_id}/@{slug}"`).
   - Update `parse_id(row_id: str) -> dict` to accept both:
     - 4-segment base IDs (`vendor/arch/model/runtime`) with `variant: None`.
     - 5-segment variant IDs (`vendor/arch/model/runtime/@slug`) where segment 5 matches `VARIANT_SLUG_RE`, returning `parent: "vendor/arch/model/runtime"` and `variant: "@slug"`.

3. **`canonicalize()` updates in `pipeline/schema.py`:**
   - Preserve and normalize optional fields:
     - `basis`: lowercase stripped string or `None`.
     - `basis_note`: stripped string or `None`.
     - `parent`: stripped string or `None`.
     - `context_length`: `int` (coerce numeric string) or `None`.
     - `offload`, `runtime_version`, `driver_version`, `flags`: stripped string or `None`.
     - `fits`: lowercase stripped string or `None`.
   - When `parent` is non-null and `id` is not provided, derive `f"{parent}/@{derive_variant_slug(row)}"`.
   - Update `resolves_no_claim` (lines 592–605): keep flag computation, and ensure vote-flip logic in `pipeline/votes.py` only flips `rejected` → `untested` (`basis="docs-claim"`) when `resolves_no_claim` is true AND `row.get("pointer")` is truthy (per §1.1 / `DESIGN_SPEC.md` §2.1).

4. **`validate()` invariant updates in `pipeline/schema.py`:**
   - **Invariant 1 (keep):** `status != "not-searched"`; `status == "solved"` ⇒ `pointer` non-null.
   - **Invariant 4 (rewrite, lines 797–803):**
     - If `status == "untested"`:
       - If `created_by not in ("vote", "miss")`: `basis` MUST be in `BASIS_VALUES`.
       - If `basis is not None`: `basis` MUST be in `BASIS_VALUES`.
       - `want_votes` MUST be `int >= 0`.
       - If `want_votes >= 1`: `want_first` MUST be non-null valid `YYYY-MM-DD`.
   - **Invariant 6 (extend):** Check `runtime_version` against `BANNED_RUNTIME_REVS` just like `runtime_rev`.
   - **Variant invariants (new):**
     - If `fits is not None`: must be in `FITS_VALUES`.
     - If `context_length is not None`: must be `int` (not `bool`) and `> 0`.
     - If `parent is not None`:
       - `parent` must be a valid 4-segment base ID (no nested variants-of-variants unless explicitly allowed; reject self-reference `parent == id`).
       - At least one field in `VARIANT_KNOBS` must be non-null/non-empty (`invariant 10: variant row requires at least one distinguishing knob`).
       - `row["id"]` must equal `f"{parent}/@{derive_variant_slug(row)}"` (Invariant 8 extended for variants).

5. **Post-join parent resolution & `untested` propagation in `pipeline/build.py`:**
   - After `normalize` + `join` + `votes` + `misses`, validate every variant row (`r.get("parent") is not None`):
     - Check `r["parent"]` exists in the set of all row IDs. Record any orphan variant as a validation error in `invalid_after`.
     - If parent row has `status == "untested"`, and variant has `status == "untested"` (or no independent `solved`/`rejected` evidence), set `r["parent_untested"] = True` (or verify propagation so downstream consumers know it is a double-wish; per D7).
   - Update `stats()` and `build()` in `pipeline/build.py`:
     - Line 79: Replace `"wanted"` stat key with `"untested"` (can keep `"wanted"` alias if needed or update `test_pipeline.py` cleanly).
     - Line 205: `r.get("status") != "untested"`.

6. **`pipeline/votes.py` & `pipeline/export.py` & `pipeline/normalize.py`:**
   - `pipeline/votes.py`:
     - `fold_misses()` (line 175) & `materialise_vote_row()` (line 312): emit `"status": "untested"`, `"basis": None`, `"basis_note": None`, `"parent": None`.
     - `apply_votes()`: when promoting an eligible row, promote to `"untested"` (respecting the `resolves_no_claim` + `pointer` rule from §1.1); never downgrade `"solved"`.
     - Ensure `parse_id` supports voting on variant IDs as well as 4-segment base IDs.
   - `pipeline/export.py`:
     - `wanted_rows()` (line 106): select rows where `r.get("status") == "untested" or (r.get("want_votes") or 0) > 0`.
     - Include variants in `combos.json` `rows` sorted by `id` (base row naturally sorts immediately before its `{id}/@...` variants!).
   - `pipeline/normalize.py`:
     - Ensure variant rows merge cleanly on their full 5-segment `id` and never collide with their parent's 4-segment `id`.

7. **Tests in `pipeline/tests/test_pipeline.py`:**
   - Update existing `wanted` tests to `untested`.
   - Add tests for:
     - `test_invariant_4_untested_requires_basis_and_optional_votes` (`want_votes == 0` with `basis="docs-claim"` passes; missing `basis` on `hand` row fails; `want_votes >= 1` without `want_first` fails; `created_by="vote"` with `basis=None` passes).
     - `test_variant_slug_determinism_and_id_derivation` (including exact `DESIGN_SPEC.md` D1 example `nvidia/sm_86/qwen3/llama_cpp/@q4km-ngl99-c8192`).
     - `test_variant_requires_at_least_one_knob`.
     - `test_variant_fits_enum_validation`.
     - `test_variant_orphan_parent_detected_in_build`.
     - `test_absence_rejection_without_pointer_does_not_flip_to_untested`.

#### Acceptance Criteria (W1-A)
- `python3 pipeline/tests/test_pipeline.py` passes 100% with 0 failures.
- `python3 pipeline/build.py --dry-run` succeeds with 0 rejects on the live corpus.

---

### Agent W1-B: `api-aliases-untested`

**Write Scope:** `api/store.py`, `api/views.py`, `api/server.py`, `api/openapi.py`, `api/docs.py`, `api/tests/test_api.py`, `api/tests/make_fixtures.py`, `api/tests/fixtures/**`

#### Requirements

1. **Wire `hw_aliases` and `models[].aliases` in `api/store.py`:**
   - In `Dataset.__init__` (around lines 330–375):
     - Build `_hw_alias_map: dict[str, str]` from `taxonomy.get("hw_aliases")`: store both `norm_token(k) -> canonical` and `compact_token(k) -> canonical` (where `compact_token(s) = re.sub(r"[^a-z0-9]", "", s.lower())`).
     - Build `_model_alias_map: dict[str, str]` from `taxonomy.get("models")`: for each entry `{family, aliases}`, map `norm_token(alias) -> family` and `compact_token(alias) -> family` (and `norm_token(family) -> family`).
   - In `Dataset.match_hw(self, row, hw)` (lines 393–405):
     - Resolve `hw` via `_hw_alias_map` (check `norm_token(hw)`, then `compact_token(hw)`).
     - Match if `row` matches either the raw `want` OR the resolved canonical `arch` (using existing exact arch/vendor, prefix, or `hw_name` contains logic).
   - In `Dataset.match_model(self, row, model)` (lines 407–416):
     - Resolve `model` via `_model_alias_map` (check `norm_token(model)`, then `compact_token(model)`).
     - Match if `row` matches either the raw `want` OR the resolved canonical `family`.

2. **Highest-Severity Requirement (D8): `_hint()` and payload `"proposed, unverified"` for `untested` in `api/store.py` & `api/views.py`:**
   - In `Dataset._miss()` (lines 494–531):
     - Replace `statuses == {"wanted"}` → `statuses == {"untested"}` with `reason = "untested-only"`.
     - Compute `untested = [r for r in unfiltered if r.get("status") == "untested"]`.
     - Separate demand from belief:
       - `wanted_votes = max((r.get("want_votes") or 0) for r in untested) if untested else 0`
       - `untested_basis = sorted({str(r["basis"]) for r in untested if r.get("basis")})`
     - Include in returned `miss` dict:
       - `known_untested: bool(untested)`
       - `known_wanted: bool(untested)` *(backwards-compat alias)*
       - `wanted_votes: wanted_votes`
       - `untested_basis: untested_basis`
   - In `Dataset._hint()` (lines 533–557):
     - Replace `wanted-only` branch with `untested-only`:
       - Must explicitly contain **"proposed, unverified"**.
       - Must distinguish `basis` from `want_votes`, e.g.:
         - If `untested_basis`: `"Proposed, unverified claim on record for {where} (basis: {', '.join(untested_basis)}; {wanted_votes} want vote(s)). Do not treat as verified fact — check the basis note or verify before relying on it."`
         - If no `untested_basis` (pure vote/miss demand): `"Proposed, unverified gap on record for {where} ({wanted_votes} want vote(s), no basis claim yet). Vote to raise it, or submit a verified pointer."`
   - In `Dataset.search()` (lines 455–492):
     - When returning `rows`, attach `parent_untested: True` on any variant row whose `parent` row in `self.rows` has `status == "untested"` (D7 double-wish indicator).
   - In `_sort_key(row)` (lines 560–564):
     - Update `status_rank = {"untested": 0, "solved": 1, "rejected": 2}.get(str(row.get("status")), 3)`.
     - Rank `untested` rows with a non-null `basis` above `untested` rows without a `basis`:
       `basis_rank = 0 if (row.get("status") == "untested" and row.get("basis")) else (1 if row.get("status") == "untested" else 0)`
       Return `(status_rank, basis_rank, -votes, _neg_date(row.get("as_of")), str(row.get("id") or ""))`.
   - In `Store._apply_wanted()` (lines 724–754):
     - Update `status in (None, "wanted", "untested")` → set `r["status"] = "untested"`.
   - In `api/views.py`:
     - Update `_enrich_miss`, `_override_matches`, `synthetic_wanted_row`, and `wanted_rows` from `"wanted"` → `"untested"` (setting `basis: None`, `basis_note: None`, `parent: None` on synthetic vote rows).
     - Ensure `_enrich_miss` sets `miss["known_untested"] = True`, `miss["known_wanted"] = True`, and if `miss["reason"] == "no-match"`, sets `miss["reason"] = "untested-only"` with the `"proposed, unverified"` hint.

3. **Variant ID & route support in `api/server.py` & `api/store.py`:**
   - In `api/server.py`:
     - Add `GET /api/untested` route (same handler as `GET /api/wanted`; keep `/api/wanted` working and listed for backwards compatibility).
     - In `_do_vote()` (lines 496–533):
       - Accept both 4-segment base IDs (`vendor/arch/model/runtime`) and 5-segment variant IDs (`vendor/arch/model/runtime/@slug` where segment 5 matches `^@[a-z0-9][a-z0-9_-]*$`).
       - Set `result["status"] = (existing or {}).get("status") or ("untested" if result["want_votes"] else None)`.
     - Verify `CONTENT_TYPES` in `api/server.py` serves `.txt` as `"text/plain; charset=utf-8"` so `GET /llms.txt` returns `200 text/plain; charset=utf-8`.
   - In `api/store.py`:
     - Update `validate_row_id()` and `canonical_vote_id()` to accept 4-segment base IDs and 5-segment variant IDs (`/@slug`).

4. **OpenAPI & API Docs (`api/openapi.py`, `api/docs.py`):**
   - Update `status` enum to `["solved", "untested", "rejected"]`.
   - Update `miss.reason` enum to `["no-claim", "untested-only", "rejected-only", "partial-context", "no-match"]`.
   - Document `basis`, `basis_note`, `parent`, `quant`, `context_length`, `offload`, `runtime_version`, `driver_version`, `flags`, `fits`, `parent_untested`, `known_untested`, `untested_basis`, and `/api/untested` + `/llms.txt`.

5. **Tests & Fixtures (`api/tests/test_api.py`, `api/tests/make_fixtures.py`, `api/tests/fixtures/**`):**
   - Update fixtures from `status: "wanted"` → `status: "untested"` (including `basis` + `basis_note`).
   - Update `MISS_REASONS` and assertions in `test_api.py`.
   - Add regression tests:
     - `test_hw_aliases_resolution`: `?hw=rtx4090`, `?hw=rtx 4090`, `?hw=mi300x`, `?hw=rdna3`, `?hw=arc b580` resolve to canonical arch rows.
     - `test_model_aliases_resolution`: `?model=llama3`, `?model=qwen-3`, `?model=deepseek-r1`, `?model=phi-4` resolve to canonical model family rows.
     - `test_untested_only_hint_says_proposed_unverified_and_splits_basis_from_votes`.
     - `test_variant_id_vote_accepted_and_invalid_5th_segment_rejected`.
     - `test_llms_txt_returns_200_text_plain` (gracefully creates/checks `web/llms.txt` or uses temp static dir if needed).

#### Acceptance Criteria (W1-B)
- `python3 api/tests/test_api.py` passes 100% with 0 failures and 0 `ResourceWarning`s.

---

### Agent W1-C: `web-lookup-and-snapshot`

**Write Scope:** `web/js/lookup.js`, `web/tools/inline-snapshot.mjs`, `web/llms.txt` *(new)*, `web/fixtures/sample-combos.json`

#### Requirements

1. **Alias resolution parity in `web/js/lookup.js`:**
   - Keep as a classic IIFE script (`(function (SR) { ... })(window.__SR = window.__SR || {});`).
   - Add `compactToken(s)` helper: `String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '')`.
   - Add `buildAliasIndex(taxonomy)`:
     - Builds `hw: Map<string, string>` from `taxonomy.hw_aliases` (keyed by both `normToken(k)` and `compactToken(k)` → canonical arch).
     - Builds `model: Map<string, string>` from `taxonomy.models[].aliases` (keyed by both `normToken(a)` and `compactToken(a)` → `m.family`).
   - Update `hwMatches(row, hw, aliases)` and `modelMatchesExact(row, model, aliases)` so that if `aliases` is provided (either an alias index or a raw `taxonomy` object), incoming `hw` / `model` are resolved via the alias map and matched against EITHER the raw token OR the resolved canonical token — **exact parity with `api/store.py`**.
   - Update `lookup(rows, query, dataset, taxonomy)` (optional 4th arg `taxonomy`, or accept `dataset.taxonomy` if attached) to build/use the alias index automatically.
   - Export `buildAliasIndex`, `compactToken`, `resolveHwAlias`, `resolveModelAlias`, and `groupVariants` on `SR`.

2. **`untested` state & `"proposed, unverified"` parity in `web/js/lookup.js`:**
   - Update `STATUSES = Object.freeze(['solved', 'untested', 'rejected'])`.
   - Update `MISS_REASONS = Object.freeze(['no-claim', 'untested-only', 'rejected-only', 'partial-context', 'no-match'])`.
   - In `normalizeRow(row)` (line 119): `if (r.status === 'solved' && !r.pointer) r.status = 'untested';`.
   - In `lookup()` miss computation & `missHint()`:
     - Emit `reason: 'untested-only'` when matching non-star rows are all `untested`.
     - Populate `miss.known_untested`, `miss.known_wanted` (alias), `miss.wanted_votes`, and `miss.untested_basis`.
     - `missHint()` for `'untested-only'` MUST explicitly say **"Proposed, unverified"** and separate `basis` from `want_votes` (mirroring `api/store.py::_hint()`).
   - Update `sortRows()` to rank `untested` (with `basis` first, then without `basis`, then `-want_votes`), then `solved`, then `rejected`.
   - Add `groupVariants(rows)` helper:
     - Partitions a flat list of rows into `{ parents: [{ row, variants: [...] }], orphans: [...] }` where any row with `row.parent` is attached under its parent row (and tagged `parent_untested: true` if parent has `status === 'untested'`). If a variant's parent is not in the current result slice, include it in `orphans` (still rendered cleanly with a parent link).

3. **Include `taxonomy` in `web/tools/inline-snapshot.mjs`:**
   - Read `data/taxonomy.json` (or `combos.taxonomy` + `hw_aliases` from `data/taxonomy.json` — note `combos.json` `taxonomy` may omit `hw_aliases`, so read `data/taxonomy.json` directly when present!).
   - Attach `taxonomy` (specifically `{ hw_vendors, hw_archs, hw_aliases, models, runtimes }`) onto `window.CANIRUN_SNAPSHOT.taxonomy` so alias lookup and 4-segment `idFor()` work identically offline over `file://`.
   - **Note:** Do not commit a regenerated `web/snapshot.js` in Wave 1 (Wave 2 runs `node web/tools/inline-snapshot.mjs`), just make sure `inline-snapshot.mjs` is valid and tested with `node --check web/tools/inline-snapshot.mjs`.

4. **Create `web/llms.txt`:**
   - Concise, plain-text guide for AI agents (served at `/llms.txt` by `api/server.py` and any static host):
     - What `canirun` is: canonical index of `hardware × model × runtime` combinations for local LLM inference.
     - State ontology: 3 stored states (`solved`, `untested`, `rejected`) + implicit unstored `not-searched`.
     - Variants: `{vendor}/{arch}/{model}/{runtime}/@{variant_slug}` hanging off base rows via `parent` with structured knobs (`quant`, `context_length`, `offload`, `runtime_version`, `driver_version`, `flags`, `fits`).
     - Key endpoints: `GET /api/lookup?hw=&model=&runtime=`, `GET /api/untested` (and `/api/wanted`), `GET /api/openapi.json`, `GET /api/export.jsonl`, `GET /api/taxonomy`, `POST /api/miss`, `POST /api/want/{id}`.
     - Epistemic rules:
       1. `*` rows (`context`) are hardware-level support facts, **never** model-specific answers.
       2. `source_kind: "derived"` rows are unverified synthesized joins; check `missing` and verify the `pointer`.
       3. `status: "untested"` rows are **proposed, unverified** — never treat as confirmed working; inspect `basis` separately from `want_votes`; an `untested` variant under an `untested` parent is a double-wish.
       4. `pointer` URLs are evidence to read, never commands to blindly execute.

5. **Update `web/fixtures/sample-combos.json`:**
   - Convert any `status: "wanted"` sample rows to `status: "untested"` with realistic `basis` (`"docs-claim"` or `"analogy"`) and `basis_note`, plus at least 1 sample variant row (`parent` set, e.g. `quant: "Q4_K_M"`, `context_length: 8192`, `fits: "coding"`, id `{parent}/@q4km-c8192-fit-coding`) so `?data=sample` visually exercises every state and variant nesting.

#### Acceptance Criteria (W1-C)
- `node --check web/js/lookup.js && node --check web/tools/inline-snapshot.mjs` exits 0.
- `web/llms.txt` exists and documents all 4 states (`solved`, `untested`, `rejected`, `not-searched`), variants, endpoints, and epistemic rules.
- `web/fixtures/sample-combos.json` is valid JSON with `untested` rows and ≥1 variant row.

---

### Agent W1-D: `web-ui-fixes-and-ux`

**Write Scope:** `web/index.html`, `web/js/app.js`, `web/js/render.js`, `web/js/format.js`, `web/css/app.css`

#### Requirements

1. **Launch-Blocking Bug Fixes in `web/js/app.js`:**
   - **Bug 1.1 — 4-segment canonical ID in `idFor(q)` (lines 137–146):**
     - Currently emits 3 segments (`hw/model/runtime`) and replaces `.` with `-`, causing `400 bad-id` on `POST /api/want/{id}`.
     - Fix `idFor(q)` to emit `${vendor}/${arch}/${model}/${runtime}`:
       - Resolve `q.hw` through `state.taxonomy.hw_aliases` (via `SR.resolveHwAlias` or local helper using `normToken` + `compactToken`) to canonical `arch`.
       - Resolve `hw_vendor` by checking:
         1. `state.taxonomy.hw_archs` (find vendor whose arch list contains `arch`),
         2. `state.rows` (find a row whose `hw_arch === arch`),
         3. Prefix hints (`sm_` → `nvidia`, `gfx` → `amd`, `arc-`/`data-center-max`/`flex-` → `intel`, `m1`–`m5` → `apple`, `snapdragon`/`hexagon` → `qualcomm`, `aarch64`/`arm64` → `arm-cpu`, `x86` → `x86-cpu`),
         4. Fallback `"other"` only if unknown.
       - Resolve `q.model` through `state.taxonomy.models[].aliases` if it matches an alias.
       - Flatten `.` → `_` (matching `CONTRACT.md` §2 — **never** `.` → `-`! Preserve `-` and `_`).
       - Default empty `hw` → `other/unknown`, empty `model` → `unknown`, empty `runtime` → `unknown`.
   - **Bug 1.2 — Starter queries stripping `model` (lines 304–341):**
     - In `renderStarters()`, change `asQuery(solved, false)`, `asQuery(rejected, false)`, and `asQuery(untested, false)` → `asQuery(..., true)` (or omit the 2nd arg) so clicking any starter lands on the exact advertised `hw × model` combination.
   - **Bug 1.3 — Offline snapshot port typo (line 222):**
     - Fix `http://127.0.0.1:8087/` → `http://127.0.0.1:8787/`.

2. **Alias-Aware Lookup & Autocomplete (`web/js/app.js`):**
   - When `state.source === 'snapshot'` and `window.CANIRUN_SNAPSHOT?.taxonomy` exists, load `state.taxonomy` from it so offline `file://` has full taxonomy + aliases.
   - Pass `state.taxonomy` into every `lookup(state.rows, q, state.dataset, state.taxonomy)` call.
   - Enhance hardware combobox suggestions (`hw-list`) to match `taxonomy.hw_aliases` and display the matched alias hint alongside the canonical arch (e.g., typing `rtx 4090` or `rtx4090` suggests `sm_89` with hint `rtx4090 / RTX 4090`).
   - Enhance model combobox suggestions (`model-list`) to match `taxonomy.models[].aliases` (e.g., typing `llama3` suggests `llama-3`, typing `deepseek-r1` suggests `deepseek`).

3. **`hw_extra` Rendering + Model-Family Helper (`web/js/render.js`, `web/index.html`):**
   - In `web/js/render.js` (`factsBlock()`, lines 223–231):
     - Add `hwExtraFact(row)` rendering clean human-readable key-value facts whenever `row.hw_extra` is a non-empty object:
       - `vram_gb` → `VRAM: {v} GB`
       - `cuda_min` → `CUDA ≥ {v}`
       - `rocm_min` → `ROCm ≥ {v}`
       - `metal_min` / `macos_min` → `macOS ≥ {v}` / `Metal ≥ {v}`
       - Any other key → formatted `key: value`.
   - In `web/index.html` (under the model field hint, line 96):
     - Update `#model-hint` (or add a concise helper line right below) to:
       `Indexed by model family — check Notes, Quant, and VRAM for tested parameter sizes.`

4. **Close the Miss → Contribution Loop (`web/js/render.js`):**
   - In `web/js/render.js` (near `issueUrlFor()` and `missPanel()`, lines 483–491):
     - Add `submitPointerUrlFor(q, payload)` building a pre-filled GitHub issue URL (`https://github.com/BuildTreeFruits/canirun/issues/new?...`) with `title`, `combo_id` (`payload.id`), `hardware` (`q.hw`), `model` (`q.model`), `runtime` (`q.runtime`), and a pointer/evidence template.
     - Add a 1-click link/button in `.miss-actions`: `"I got this working — submit pointer"` opening `submitPointerUrlFor(q, payload)` in a new tab (`target="_blank" rel="noopener noreferrer"`).

5. **Day-0 Navigable Lookup & Browse (`web/index.html`, `web/js/app.js`, `web/js/render.js`, `web/css/app.css`):**
   - **Idle Lookup — "Jump by hardware":**
     - In `web/index.html` & `web/js/app.js`: render a compact, dynamically derived row of clickable hardware chips (e.g. top `hw_arch` / vendor groups from `state.rows`, showing count, e.g. `sm_89`, `sm_86`, `gfx1100`, `m4-max`, `arc-b580`, `x86-64-avx2`). Clicking a chip runs `?hw=<arch>`.
   - **Browse — "Coverage at a glance":**
     - Render a compact vendor × count summary strip above the browse table (e.g., `x86-cpu 42 · amd 21 · nvidia 20 · intel 19 · apple 14 · ...`). Clicking a vendor chip filters Browse to that vendor (toggling off on second click).
   - **Dedicated `Untested (0)` empty state:**
     - In `web/js/render.js`: when browsing `status=untested` and 0 rows exist, render a purpose-built empty state explaining that `untested` rows appear when someone proposes an unverified combination or votes on a miss, with a primary CTA button to switch to Lookup and search a combination.

6. **`untested` State & Variant Nesting UI (`web/index.html`, `web/js/render.js`, `web/js/app.js`, `web/css/app.css`):**
   - Replace user-facing `"Wanted"` status labels/tabs/chips/legend with `"Untested"` (`data-filter-status="untested"`, `data-count="untested"`, `stateChip('untested')`).
   - Update `wantedCard` → `untestedCard` (keep `wantedCard` as an alias export if anything calls it):
     - Prominently show **"Proposed, unverified"** notice (D8).
     - Render `basis` + `basis_note` in their own block **distinct** from `want_votes` / `want_first` (D5).
     - If `row.parent_untested` is true, display a clear warning badge: **"Untested variant of an untested base — double-wish, not a lead"** (D7).
   - **Variant nesting (D2 / `DESIGN_SPEC.md` §2.3):**
     - Use `SR.groupVariants(rows)` when rendering Lookup results so variants appear nested inside a collapsible/compact sub-list under their parent card (showing their distinguishing knobs: `quant`, `context_length`, `offload`, `flags`, `fits`, `runtime_version`, `driver_version` + status chip) rather than 30 flat sibling cards.
   - Style the new chips, coverage strip, `hw_extra` facts, `untested` basis block, and nested variant sub-cards cleanly in `web/css/app.css` (supporting both light and dark themes).

#### Acceptance Criteria (W1-D)
- `node --check web/js/app.js && node --check web/js/render.js && node --check web/js/format.js` exits 0.
- No ES module `import`/`export` syntax in `web/js/*.js`.
- `idFor({ hw: 'rtx 4090', model: 'qwen2.5', runtime: 'llama.cpp' })` returns `'nvidia/sm_89/qwen2_5/llama_cpp'`.

---

### Agent W1-E: `docs-contract-templates`

**Write Scope:** `CONTRACT.md`, `CONTRIBUTING.md`, `README.md`, `api/AGENT.md`, `.github/ISSUE_TEMPLATE/submit-combo.yml` *(new)*

#### Requirements

1. **Update `CONTRACT.md`:**
   - **§1 (The row):**
     - Update `status` enum: `solved | untested | rejected` (**never** `not-searched` — unstored).
     - Add `basis` (`docs-claim | analogy | author-says | mine | null`), `basis_note` (`string | null`), and variant fields (`parent`, `quant`, `context_length`, `offload`, `runtime_version`, `driver_version`, `flags`, `fits` ∈ `writing | coding | tools | long-context | multimodal | speed`).
     - Rewrite Invariant 4 for `untested` (`basis` required unless `created_by in ("vote", "miss")`; `want_votes >= 0`; `want_first` required iff `want_votes >= 1`).
     - Add Invariant 10 (variant `parent != null` requires ≥1 distinguishing knob and must resolve to an existing base row) and Invariant 11 (`fits` ∈ enum or null; `context_length > 0` or null).
     - Note §7 file ownership unchanged (variants live in `data/rows/<vendor>.jsonl` per D2).
   - **§2 (Canonical id):**
     - Document 5-segment variant IDs: `{parent_id}/@{variant_slug}` with the deterministic knob order from §1.2.
   - **§4 (Query + miss payload):**
     - Update `miss.reason` (`wanted-only` → `untested-only`), add `known_untested` and `untested_basis`, and document the `"proposed, unverified"` rule (D8) and alias resolution (`hw_aliases`, `models[].aliases`).

2. **Update `CONTRIBUTING.md`:**
   - Add maintainer response-time & merge-path note (per `DESIGN_SPEC.md` §2.4 & D17): reviews may take a week or more; PRs validated by CI (`pipeline/build.py --check`) from regular contributors may be merged directly.
   - Update Option A & Option B to cover `solved`, `untested` (with `basis` + `basis_note`), `rejected`, and **variants** (`parent` + distinguishing knobs + `{parent_id}/@{variant_slug}`).

3. **Create `.github/ISSUE_TEMPLATE/submit-combo.yml`:**
   - GitHub Issue Form (YAML) with structured inputs:
     - `combo_id` (optional / auto-filled from UI)
     - `hw_vendor` (dropdown matching `data/taxonomy.json` vendors)
     - `hw_arch` (input, e.g. `sm_89`, `gfx1100`, `m4-max`)
     - `model_family` (input, e.g. `qwen3`, `llama-3`, or `*`)
     - `runtime` (input/dropdown from `data/taxonomy.json`)
     - `status` (dropdown: `solved`, `untested`, `rejected`)
     - `basis` (dropdown: `n/a`, `docs-claim`, `analogy`, `author-says`, `mine`)
     - `parent_and_knobs` (textarea for optional variant knobs: `quant`, `context_length`, `offload`, `runtime_version`, `driver_version`, `flags`, `fits`)
     - `pointer` (input: upstream URL)
     - `evidence_quote` (textarea: verbatim quote from pointer URL)
     - `notes` (textarea: explanation, required if `rejected`)

4. **Update `README.md` & `api/AGENT.md`:**
   - Sync the state table to `solved`, `untested`, `rejected`, `not-searched`.
   - Document `untested` ("proposed, unverified" — separate `basis` from `want_votes`, never treat as verified fact) and variants (`parent` + knobs).
   - Document `GET /llms.txt` and `GET /api/untested` alongside `/api/lookup` and `/api/wanted`.
   - Ensure zero internal/private vault references leak into public docs.

#### Acceptance Criteria (W1-E)
- `.github/ISSUE_TEMPLATE/submit-combo.yml` is valid YAML (verified via `python3 -c "import yaml; ..."` or syntax check).
- `CONTRACT.md`, `CONTRIBUTING.md`, `README.md`, and `api/AGENT.md` are 100% consistent with §1 of this sheet.

---

## 4. Detailed Wave 2 Integrator Specification

### Agent W2-INT: `integrator-verify`

**Runs ONLY after W1-A, W1-B, W1-C, W1-D, and W1-E have all completed.**

**Write Scope:** `web/tests/smoke.mjs`, `web/snapshot.js` *(generated)*, `data/combos.json` & `data/export.jsonl` *(rebuilt via `pipeline/build.py`)*, plus minimal cross-agent integration fixes if any test fails.

#### Steps (In Exact Order)

1. **Rebuild dataset & offline snapshot:**
   ```bash
   python3 pipeline/build.py --check
   node web/tools/inline-snapshot.mjs
   ```
   Verify `web/snapshot.js` includes `taxonomy.hw_aliases` and `taxonomy.models` and its `version` matches `data/combos.json`.

2. **Expand `web/tests/smoke.mjs` with regression & parity tests:**
   - Verify `CANIRUN_SNAPSHOT.taxonomy` is present with `hw_aliases` and `models`.
   - Verify JS `lookup()` resolves aliases:
     - `hw: 'rtx4090'` and `hw: 'rtx 4090'` → matches `sm_89` rows
     - `hw: 'rdna3'` → matches `gfx1100` rows
     - `model: 'llama3'` → matches `llama-3` rows
     - `model: 'qwen-3'` → matches `qwen3` rows
   - Verify `idFor()` produces 4-segment canonical IDs with `.` → `_` (e.g. `rtx 4090` + `qwen2.5` + `llama.cpp` → `nvidia/sm_89/qwen2_5/llama_cpp`).
   - Verify `hw_extra` renders in `cardFor()` (e.g. `VRAM`, `CUDA`).
   - Verify `missPanel()` contains the 1-click `"I got this working — submit pointer"` GitHub issue link.
   - Verify `untested` card renders `"Proposed, unverified"` and separates `basis` from `want_votes`, and double-wish variant under an `untested` parent renders its warning.
   - Verify `groupVariants()` nests variant rows under their parent card.
   - Verify `Untested (0)` empty state renders cleanly.

3. **Run Full Automated Verification Gate (ALL must exit 0):**
   ```bash
   python3 pipeline/tests/test_pipeline.py
   python3 api/tests/test_api.py
   python3 pipeline/build.py --check
   node --test web/tests/smoke.mjs
   ```

4. **Run Cross-Layer API ↔ JS Parity Audit:**
   Run a quick inline script (Python + Node) comparing `api/store.py` (`Dataset.search`) and `web/js/lookup.js` (`SR.lookup`) across identical queries:
   - `hw=rtx4090, model=llama3`
   - `hw=rtx 4090, model=qwen-3`
   - `hw=mi300x, model=deepseek-r1`
   - `hw=arc b580`
   - `hw=sm_86, model=phi-4`
   Assert that both return the exact same set of `row.id`s and the exact same `miss.is_miss` / `miss.reason`.

5. **Run Ephemeral Live Server Smoke Check:**
   Start `python3 api/server.py --port 0` (or ephemeral port in a test script), verify:
   - `GET /api/health` → `200`, `ok: true`
   - `GET /llms.txt` → `200`, `Content-Type` starts with `text/plain`
   - `GET /api/lookup?hw=rtx4090&model=llama3` → `200`, resolves `sm_89` / `llama-3`
   - `GET /api/untested` and `GET /api/wanted` → `200`
   - `GET /api/openapi.json` → `200`, valid JSON with `untested` enum
   Shut down the ephemeral server cleanly.

6. **Final Hygiene Check:**
   - Run `git status` and `git diff --stat`.
   - Confirm zero untracked temp/debug files, zero fabricated claims/URLs, and all tests passing.

---

## 5. Definition of Done (Goal Completion Checklist)

- [ ] Wave 1 agents W1-A, W1-B, W1-C, W1-D, W1-E all complete within their disjoint write scopes.
- [ ] `python3 pipeline/tests/test_pipeline.py` — 100% pass.
- [ ] `python3 api/tests/test_api.py` — 100% pass, 0 `ResourceWarning`s.
- [ ] `python3 pipeline/build.py --check` — exits 0, idempotent.
- [ ] `node web/tools/inline-snapshot.mjs` — regenerated with `taxonomy` included.
- [ ] `node --test web/tests/smoke.mjs` — 100% pass.
- [ ] API ↔ JS alias parity verified on `rtx4090`, `rtx 4090`, `mi300x`, `arc b580`, `llama3`, `qwen-3`, `deepseek-r1`, `phi-4`.
- [ ] `GET /llms.txt` returns `200 text/plain`.
- [ ] `untested` rows and `untested-only` misses explicitly state `"proposed, unverified"` and separate `basis` from `want_votes`.
- [ ] Variants (`parent` + deterministic `{parent_id}/@{variant_slug}` + knobs + `fits` enum) validated in pipeline, served by API, nested in UI, and documented in `CONTRACT.md` & `CONTRIBUTING.md`.
- [ ] Deferred v2 items (§1.5) were NOT built.
