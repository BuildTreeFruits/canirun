# CONTRACT — canirun combo-index v1

Frozen schema and interface contract between the scraper corpus, the build pipeline, the HTTP API, and the web UI.

---

## 1. The row

Row instances are stored as **JSONL** in `data/rows/<vendor>.jsonl` — one JSON object per line.
Every row below is complete: fields not listed as "optional" must be present.

```json
{
  "id": "nvidia/sm_86/qwen3/llama_cpp",
  "status": "solved",
  "source_kind": "derived",
  "provisional": false,

  "hw_vendor": "nvidia",
  "hw_arch": "sm_86",
  "hw_name": "RTX 3090 / A6000 class",
  "hw_extra": { "vram_gb": 24, "cuda_min": "11.8" },

  "model_family": "qwen3",
  "model_rev": null,
  "quant": "Q4_K_M",

  "runtime": "llama.cpp",
  "runtime_rev": "b6400",

  "pointer": "https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#cuda",
  "notes": "llama.cpp CUDA backend builds for sm_86 via -DGGML_CUDA=ON.",
  "measurement": null,
  "pointer_alive": true,

  "as_of": "2026-11-22",
  "reported_by": "scraper:llama_cpp_backends",
  "first_seen": "2026-11-22",
  "updated": "2026-11-22",

  "want_votes": 0,
  "want_first": null,
  "want_requesters": [],

  "evidence": [
    { "url": "https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md",
      "quote": "Make sure to have the CUDA toolkit installed.",
      "kind": "upstream-doc" }
  ],

  "missing": ["model"],
  "created_by": "derived"
}
```

### Required, always

| field | type | rule |
|---|---|---|
| `id` | string | see §2 |
| `status` | enum | `solved` \| `untested` \| `rejected` (**never** `not-searched` — it is unstored) |
| `source_kind` | enum | `scraped` \| `derived` \| `hand` \| `author-claim` |
| `hw_vendor` | enum | `nvidia` \| `amd` \| `intel` \| `apple` \| `qualcomm` \| `arm-cpu` \| `x86-cpu` \| `other` |
| `hw_arch` | string | `sm_86`, `gfx1100`, `m4-max`, `snapdragon-x-elite`, `x86-64-avx2`, … |
| `model_family` | string | canonical family slug from `data/taxonomy.json`, or `*` (see §3) |
| `runtime` | string | slug from `data/taxonomy.json` `runtimes[].slug` |
| `as_of` | `YYYY-MM-DD` | **mandatory**. Rows without a date are rejected by the validator |
| `reported_by` | string | `scraper:<source_key>`, `curated:v1`, or contributor handle |
| `first_seen`, `updated` | `YYYY-MM-DD` | set by the pipeline, not by scrapers |
| `pointer_alive` | bool | set by link-checker; `true` at creation |
| `want_votes` | int | ≥ 0, `0` at creation |
| `want_first` | date\|null | required iff `want_votes >= 1` (nullable when `want_votes == 0`) |
| `want_requesters` | string[] | capped at 10 for display; `want_votes` is authoritative |
| `evidence` | object[] | ≥ 1. Each `{url, quote, kind}`, `kind` ∈ `upstream-doc`\|`package-table`\|`model-repo`\|`release`\|`issue`\|`community` |

### Optional / nullable

`provisional`, `hw_name`, `hw_extra` (object, default `{}`), `model_rev`, `quant`, `runtime_rev`,
`pointer`, `notes`, `measurement` (`{tok_s, source}` or null), `missing` (string[], default `[]`),
`created_by` (`scraper`\|`derived`\|`hand`\|`vote`\|`miss`),
`basis` (`docs-claim`\|`analogy`\|`author-says`\|`mine`\|null — required on `untested` rows unless `created_by` ∈ `vote`\|`miss`),
`basis_note` (string\|null),
and variant fields: `parent` (string\|null, base row `id`), `context_length` (int > 0\|null),
`offload` (string\|null), `runtime_version` (string\|null), `driver_version` (string\|null),
`flags` (string\|null), `fits` (`writing`\|`coding`\|`tools`\|`long-context`\|`multimodal`\|`speed`\|null).

### Invariants (enforced by `pipeline/schema.py`)

1. `status != "not-searched"`; `status == "solved"` ⇒ `pointer` non-null.
2. `source_kind == "scraped"` ⇒ `pointer` non-null, and the row is **complete**: either
   `len(missing) == 0`, or `missing == ["model"]` with `model_family == "*"`.
   *(A `*` row names the dimension it omits — that is what makes it honest, not incomplete.)*
3. `source_kind == "derived"` ⇒ `len(missing) >= 1` — a derived row **states what it lacks**.
4. `status == "untested"` ⇒ `basis` ∈ `("docs-claim", "analogy", "author-says", "mine")` unless
   `created_by` ∈ `("vote", "miss")` (where `basis` may be `null`); `want_votes >= 0`; and
   `want_first` is non-null iff `want_votes >= 1`.
5. `status == "rejected"` ⇒ `notes` non-null (why it fails on this card is the whole value).
6. `runtime_rev` (and `runtime_version`) is never the string `latest`, `master`, `main`, `HEAD`, or empty.
7. `as_of` matches `^\d{4}-\d{2}-\d{2}$` and is not in the future.
8. `id` must equal the slug of `hw_vendor` + `hw_arch` + `model_family` + `runtime` (§2), or `{parent_id}/@{variant_slug}` for variants.
9. `model_family == "*"` ⇒ `"model"` ∈ `missing` (the `*` is always declared, whatever the kind).
10. `parent != null` ⇒ at least one of `(quant, context_length, offload, runtime_version, driver_version, flags, fits)` is non-null/non-empty, and `parent` resolves to an existing base row `id` in the dataset.
11. `fits` ∈ `("writing", "coding", "tools", "long-context", "multimodal", "speed")` or `null`; `context_length > 0` or `null`.

## 2. Canonical id

`id = f"{hw_vendor}/{hw_arch}/{model_family_id}/{runtime_id}"`

**Normative ID rule:**

1. Each of the four segments is lowercased (`[A-Z]` → `[a-z]`).
2. Every `.` inside a segment becomes `_`. This is the *only* transform.
3. `_` and `-` pass through unchanged. No other character is rewritten.

Examples:

| field (kept verbatim in row) | id segment |
|---|---|
| `"runtime": "llama.cpp"` | `llama_cpp` |
| `"runtime": "mlx-lm"` | `mlx-lm` |
| `"runtime": "vllm"` | `vllm` |
| `"model_family": "qwen2.5"` | `qwen2_5` |
| `"model_family": "llama-3.1"` | `llama-3_1` |
| `"model_family": "*"` | `*` |
| `"hw_arch": "sm_86"` | `sm_86` |
| `"hw_arch": "m4-pro"` | `m4-pro` |

Full IDs: `nvidia/sm_86/qwen2_5/llama_cpp`, `apple/m4-pro/*/mlx-lm`, `amd/gfx1100/*/vllm`,
`other/ascend-910b/llama-3/llama_cpp`.

**Hyphens are never rewritten.** `mlx-lm` stays `mlx-lm` (it has no dot, so no transform applies);
separators are not normalized to `_`. The only character that becomes `_` is a literal dot.

The **fields** on the row object are never rewritten — only `id`. `"runtime": "llama.cpp"` stays
exactly that in the row; the taxonomy slug is `llama.cpp`. Same for `model_family`, which may
carry dots so that `qwen2.5` and `qwen3` remain distinguishable families.

One row per `id` per stored set. The normalizer merges rows sharing an `id` (see §5).
IDs are permanent: once a row is stored its `id` is the vote key and the deep link.

### Variant IDs (5 segments)

When `parent` is non-null, the canonical `id` is:

`{parent_id}/@{variant_slug}`

`variant_slug` is derived deterministically in this fixed knob order (omitting `null`/empty knobs, joining present parts with `-`):

1. `quant`: lowercase, strip `_` and non-`[a-z0-9]` (e.g. `Q4_K_M` → `q4km`)
2. `offload`: lowercase, strip `=` and spaces, keep `[a-z0-9]` (e.g. `ngl=99` → `ngl99`)
3. `context_length`: `c{int}` (e.g. `8192` → `c8192`)
4. `runtime_version`: `rv-{slug}` (`[a-z0-9]`, `.` → `_`)
5. `driver_version`: `drv-{slug}` (`[a-z0-9-]`, `.` → `_`)
6. `flags`: `f-{slug}` (lowercase tokens joined by `-`, leading `--` stripped)
7. `fits`: `fit-{fits}` (exact enum value)

Example: `nvidia/sm_86/qwen3/llama_cpp/@q4km-ngl99-c8192`. `variant_slug` must match `^@[a-z0-9][a-z0-9_-]*$`.

## 3. The `*` model family (hardware claims)

When a source makes a claim about **hardware × runtime** only (a backend works on an architecture,
regardless of which model you run), `model_family` is `"*"` and `missing` contains `"model"`.
A `*` row means *"this backend supports this hardware"*, **not** *"this card runs model X"*.
The UI and API never present a `*` row as if it answered a specific model query; it renders as
**"applies to all models"** context, and a specific-model query for hardware that only has `*` rows
returns `miss.partial: true` (`reason: "partial-context"`) with the `*` rows attached under `context`.

## 4. Query + miss payload (`GET /api/lookup`, static fallback `combos.json`)

Query params (all optional, unknown params ignored): `hw`, `model`, `runtime`, `status`,
`kind` (`source_kind`), `q` (free text), `limit` (default 50, max 500).

Matching: `hw` matches `hw_arch` exactly, else `hw_vendor` exactly, else prefix, resolving
`taxonomy.hw_aliases` (via normalized token and compact alphanumeric key). `model` matches `model_family`
exactly, else contains, resolving `taxonomy.models[].aliases`; a `*` row matches any model
**as context only** (see §3). `runtime` matches slug, then display name.

Response:

```json
{
  "query": {"hw": "sm_86", "model": "qwen3", "runtime": null, "status": null,
            "kind": null, "q": null, "limit": 50},
  "rows": [ { "...row..." } ],
  "context": [ { "...row with model_family '*'..." } ],
  "miss": {
    "is_miss": true,
    "reason": "no-claim",
    "partial": false,
    "hint": "No claim on record for sm_86 × qwen3. Hardware-level support exists for llama.cpp; no model-specific claim.",
    "known_wanted": false,
    "wanted_votes": 0,
    "known_untested": false,
    "untested_basis": [],
    "last_checked": null,
    "counts": {"exact": 0, "context": 2}
  },
  "query_id": "ab12cd34",
  "generated_at": "2026-11-22T06:12:00Z",
  "dataset": {"rows": 317, "as_of": "2026-11-23", "version": "2026-11-23.37"}
}
```

`miss.reason` ∈ `no-claim` (nothing at all) \| `untested-only` (only `untested` rows matched) \|
`rejected-only` (only `rejected` rows matched) \| `partial-context` (only `*` rows matched) \|
`no-match` (query produced nothing, including no context).

For `untested` rows, API hints and UI payloads MUST explicitly state **"proposed, unverified"**
and surface `basis` / `basis_note` separately from `want_votes` — never present an `untested`
row as a verified fact. `known_wanted` and `wanted_votes` are kept alongside `known_untested`
and `untested_basis` for backwards compatibility.

`miss.is_miss` is `true` iff `len(rows) == 0`; `context` rows never count as an answer.
The `miss` object is **always** present.

## 5. Normalizer / merge rules (`pipeline/normalize.py`)

- Input: `scrapers/out/<source_key>.jsonl` (raw emits, any order, duplicates allowed).
- Output: `data/rows/<vendor>.jsonl`, sorted by `id` for minimal diffs.
- Merge on `id`. Higher `source_kind` rank wins the base: `author-claim` > `hand` > `scraped` > `derived`.
- Within equal `source_kind` rank: upstream evidence (`upstream-doc` / `package-table` / `release`) beats community issues (`issue` / `community`); then prefer the row with more non-null fields; tie → later `as_of`.
- **Model-specific beats `*`.** If rows sharing an `id` disagree on `model_family` (`*` vs a specific family), the model-specific family wins.
- `first_seen` = min across merged, `updated` = max, `as_of` = winner's.
- `evidence` = union, deduped on `url` (cap 8).
- A row is **never deleted** by the normalizer; upstream disappearance is tracked by `pipeline/check_links.py` (`pointer_alive: false`).

## 6. Taxonomy (`data/taxonomy.json`)

```json
{
  "version": "1",
  "hw_vendors": {"nvidia": {"label": "NVIDIA"}, "...": {}},
  "runtimes": [{"slug": "llama.cpp", "label": "llama.cpp", "repo": "..."}],
  "models": [{"family": "qwen3", "label": "Qwen3", "aliases": ["qwen-3", "qwen3.5"], "vendor": "alibaba"}],
  "quants": ["Q4_K_M", "Q8_0", "fp8", "awq", "gptq", "mlx-4bit"],
  "hw_archs": {"nvidia": ["sm_75", "sm_80", "sm_86", "sm_89", "sm_90", "sm_100", "sm_120"]},
  "hw_aliases": {"rtx4090": "sm_89", "m4_pro": "m4-pro", "rx7900xtx": "gfx1100"}
}
```

The UI uses `hw_vendors`, `hw_archs`, `hw_aliases`, `models`, and `runtimes` for search suggestions and alias resolution; the scrapers and pipeline use `models` for family canonicalization and `runtimes` for canonical slugs. Scrapers may also emit newly discovered architectures or model families to `data/taxonomy.extensions.json`, which `pipeline/build.py` merges automatically.

## 7. Module boundaries

| Subsystem | Files written / owned |
|---|---|
| **Scrapers** | `scrapers/sources/*.py`, `scrapers/out/*.jsonl`, `scrapers/runs.jsonl`, `data/taxonomy.extensions.json` |
| **Pipeline** | `pipeline/*.py`, `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl`, `data/votes.json`, `data/misses.jsonl` |
| **Frontend** | `web/**` (`web/snapshot.js` generated via `node web/tools/inline-snapshot.mjs`) |
| **API & Core** | `CONTRACT.md`, `data/taxonomy.json`, `README.md`, `scripts/*.py`, `api/**` |

Variants live in `data/rows/<vendor>.jsonl` alongside their base rows.
