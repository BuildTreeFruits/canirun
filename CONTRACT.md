# CONTRACT — canirun combo-index v1

Frozen interface between the scraper pipeline, the export, the vote service and the web UI.
**Do not change a key name or enum value without messaging `lead`.** Everything here is derived
from the blueprint (`local-inference-solutions-index.md`) with its open decisions resolved by lead.

---

## 1. The row

A row instances are stored as **JSONL** in `data/rows/<vendor>.jsonl` — one object per line.
Every row below is complete: fields not listed as "optional" must be present.

```json
{
  "id": "nvidia/sm_86/qwen3/llama.cpp",
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
| `hw_arch` | string | `sm_86`, `gfx1100`, `m4`, `snapdragon-x-elite`, `x86-64-avx2`, … snake_case |
| `model_family` | string | snake_case, or `*` (see §3) |
| `runtime` | string | slug from `data/taxonomy.json` `runtimes[].slug` |
| `as_of` | `YYYY-MM-DD` | **mandatory**. Rows without a date are rejected by the validator |
| `reported_by` | string | `scraper:<source_key>` or handle |
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

### Invariants (the validator enforces these)

1. `status != "not-searched"`; `status == "solved"` ⇒ `pointer` non-null.
2. `source_kind == "scraped"` ⇒ `pointer` non-null, and the row is **complete**: either
   `len(missing) == 0`, or `missing == ["model"]` with `model_family == "*"`.
   *(A `*` row names the dimension it omits — that is what makes it honest, not incomplete.
   The earlier "scraped ⇒ missing == []" reading made every scraped hardware claim invalid
   by construction, which would have forced honest rows to masquerade as `derived`.)*
3. `source_kind == "derived"` ⇒ `len(missing) >= 1` — a derived row **states what it lacks**.
4. `status == "untested"` ⇒ `basis` ∈ `("docs-claim", "analogy", "author-says", "mine")` unless
   `created_by` ∈ `("vote", "miss")` (where `basis` may be `null`); `want_votes >= 0`; and
   `want_first` is non-null iff `want_votes >= 1`.
5. `status == "rejected"` ⇒ `notes` non-null (why it fails on this card is the whole value).
6. `runtime_rev` is never the string `latest`, `master`, `main`, `HEAD`, or empty.
7. `as_of` matches `^\d{4}-\d{2}-\d{2}$` and is not in the future.
8. `id` must equal the slug of `hw_vendor` + `hw_arch` + `model_family` + `runtime` (§2), or `{parent_id}/@{variant_slug}` for variants.
9. `model_family == "*"` ⇒ `"model"` ∈ `missing` (the `*` is always declared, whatever the kind).
10. `parent != null` ⇒ at least one of `(quant, context_length, offload, runtime_version, driver_version, flags, fits)` is non-null/non-empty, and `parent` resolves to an existing base row `id` in the dataset.
11. `fits` ∈ `("writing", "coding", "tools", "long-context", "multimodal", "speed")` or `null`; `context_length > 0` or `null`.

## 2. Canonical id

`id = f"{hw_vendor}/{hw_arch}/{model_family_id}/{runtime_id}"`

**The one rule, stated once (normative — this supersedes any earlier wording):**

1. Each of the four segments is lowercased (`[A-Z]` → `[a-z]`).
2. Every `.` inside a segment becomes `_`. This is the *only* transform.
3. `_` and `-` pass through unchanged. No other character is rewritten.

Consequences, which is where the confusion lived:

| field (kept verbatim) | id segment |
|---|---|
| `"runtime": "llama.cpp"` | `llama_cpp` |
| `"runtime": "mlx-lm"` | `mlx-lm` |
| `"runtime": "vllm"` | `vllm` |
| `"model_family": "qwen2.5"` | `qwen2_5` |
| `"model_family": "llama-3.1"` | `llama-3_1` |
| `"model_family": "*"` | `*` |
| `"hw_arch": "sm_86"` | `sm_86` |
| `"hw_arch": "m4_pro"` | `m4_pro` |

So: `nvidia/sm_86/qwen2_5/llama_cpp`, `apple/m4_pro/*/mlx-lm`, `amd/gfx1100/*/vllm`,
`other/ascend-910b/llama-3/llama_cpp`.

**Hyphens are never rewritten.** `mlx-lm` stays `mlx-lm` (it has no dot, so no transform applies);
separators are not normalised to `_`. The only thing that becomes `_` is a literal dot.

The **fields** are never rewritten — only the id. `"runtime": "llama.cpp"` stays exactly that in
the row; the taxonomy slug is already `llama.cpp`. Same for `model_family`, which is allowed to
carry dots so that `qwen2.5` and `qwen3` remain distinguishable families.

One row per id per *stored set*. The normalizer merges rows sharing an id (see §5).
Ids are permanent: once a row is stored its id is the vote key and the deep link, so a change here
is a data migration. That is why this is nailed down before the corpus grows.

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

When a source makes a claim about **hardware × runtime** only (a backend works on an arch,
regardless of which model you run), `model_family` is `"*"` and `missing` contains `"model"`.
These are the honest shape of the seed corpus — see the blueprint's "Probe finding".
A `*` row means *"this backend supports this card"*, **not** *"this card runs model X"*.
The UI must never render a `*` row as if it answered a specific model query; it renders as
**"applies to all models"** context, and a specific-model query for a card with only `*` rows
still returns `miss.partial: true` with the `*` rows attached as context.

## 4. Query + miss payload (`api/lookup.py`, static fallback `combos.json`)

Query params (all optional, unknown params ignored): `hw`, `model`, `runtime`, `status`,
`kind` (`source_kind`), `q` (free text), `limit` (default 50, max 500).

Matching: `hw` matches `hw_arch` exactly, else `hw_vendor` exactly, else prefix, resolving
`taxonomy.hw_aliases` (via `normToken` and compact alphanumeric key). `model` matches `model_family`
exactly, else contains, resolving `taxonomy.models[].aliases`; a `*` row matches any model
**as context only** (see §3). `runtime` matches slug, then display name.

Response:

```json
{
  "query": {"hw": "sm_86", "model": "qwen3", "runtime": null, "status": null,
            "kind": null, "q": null, "limit": 50},
  "rows": [ { ...row... } ],
  "context": [ { ...row with model_family "*" ...} ],
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
  "dataset": {"rows": 412, "as_of": "2026-11-22", "version": "2026-11-22.1"}
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
The miss object is **always** present when `is_miss` is true. An empty array alone is a bug.

## 5. Normalizer / merge rules (`pipeline/normalize.py`)

- Input: `scrapers/out/<source_key>.jsonl` (raw emits, any order, dupes allowed).
- Output: `data/rows/<vendor>.jsonl`, sorted by `id` for smallest diffs.
- Merge on `id`. Higher `source_kind` rank wins the base: `author-claim` > `hand` > `scraped` > `derived`.
- Within equal rank: prefer the row with more non-null fields; tie → later `as_of`.
- **Model-specific beats `*`.** If rows sharing an id disagree on `model_family` (`*` vs a specific
  family — possible only when a dot-free id collision occurs), the model-specific family wins.
  A complete claim must never be downgraded to "applies to all models": that would turn a `scraped`
  row into an invalid one under invariant 2.
- `first_seen` = min across merged, `updated` = max, `as_of` = winner's.
- `evidence` = union, deduped on `url` (cap 8).
- A row is **never deleted**; upstream disappearance is the link-checker's job (`pointer_alive: false`).

## 6. Taxonomy (`data/taxonomy.json`)

```json
{
  "version": "1",
  "hw_vendors": {"nvidia": {"label": "NVIDIA"}, ...},
  "runtime": [{"slug": "llama.cpp", "label": "llama.cpp", "repo": "...", "kinds": ["gguf","ggml"]}, ...],
  "models": [{"family": "qwen3", "label": "Qwen3", "aliases": ["qwen-3","qwen3.5"], "vendor": "alibaba"}],
  "quants": ["Q4_K_M", "Q8_0", "fp8", "awq", "gptq", "mlx-4bit", ...],
  "hw_archs": {"nvidia": ["sm_75","sm_80","sm_86","sm_89","sm_90","sm_100","sm_120"], ...}
}
```

The UI uses `hw_vendors` and `runtime` for its dropdowns; the scrapers use `models` for family
canonicalisation and `runtime` for slugs. **Lead owns this file**; scraper agents may append
`hw_archs` values and model families via their own `data/taxonomy.extensions.json`, which the
pipeline merges. Do not edit `data/taxonomy.json` directly.

## 7. File ownership

| owner | writes |
|---|---|
| **scraper** | `scrapers/sources/*.py`, `scrapers/out/*.jsonl`, `scrapers/runs.jsonl`, `data/taxonomy.extensions.json` |
| **pipeline** | `pipeline/*.py`, `data/rows/*.jsonl`, `data/combos.json`, `data/votes.json`, `data/misses.jsonl` |
| **frontend** | `web/**` |
| **lead** | `CONTRACT.md`, `data/taxonomy.json`, `README.md`, `scripts/serve.py`, `api/**` final integration |

Nobody edits another owner's files. If a contract change is unavoidable, message `lead` first.
File ownership above is unchanged for variants: variants live in `data/rows/<vendor>.jsonl` alongside their base rows.
