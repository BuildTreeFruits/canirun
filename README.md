# solve.run

A canonical index of **hardware × model × runtime** combinations for local LLM inference. It answers whether a working path exists for a specific card, model family, and engine—or whether that combination is a recorded gap or has never been searched.

## What it is

Every combination in the index falls into one of four states:

| State | Meaning | Stored? |
|---|---|---|
| `solved` | A working path exists and is pointed to | Yes, with `as_of` date |
| `wanted` | Someone looked, nothing found, ≥ 1 person wants it | Yes, with `want_votes` + `want_first` |
| `rejected` | Tried, does not work on this hardware | Yes, with `notes` explaining why |
| `not-searched` | Nobody has claimed anything | **No** — absence of a row *is* the state |

## Quick start

```bash
python3 scripts/serve.py          # Start local server at http://127.0.0.1:8787 (API docs at /api/docs)
python3 pipeline/build.py         # Rebuild data/combos.json, data/export.jsonl, and data/rows/*.jsonl
python3 scrapers/run_all.py       # Re-scrape upstream sources (1 req/s, cached)
```

The site also works without a server: open `web/index.html` directly and it falls back to reading `data/combos.json`. Running `scripts/serve.py` enables the live `/api/want/{id}` voting and `/api/miss` logging endpoints.

## API & Agent integration

Query combinations directly over HTTP:

```bash
curl -s "http://127.0.0.1:8787/api/lookup?hw=sm_86&model=qwen3"
curl -s -X POST "http://127.0.0.1:8787/api/want/nvidia%2Fsm_86%2Fqwen3%2Fllama_cpp" -H "X-Voter: agent:my-tool"
```

See `/api/docs` (served by `scripts/serve.py`) or `api/AGENT.md` for the full endpoint reference and paste-ready agent prompt snippet.

## Data honesty model

Upstream documentation rarely publishes a full hardware × model × runtime matrix; instead, projects publish backend build docs and package compatibility tables. To avoid presenting synthesized joins as verified facts, every row carries a `source_kind` and `missing` list (enforced by `CONTRACT.md`):

- **`scraped`** — Extracted directly from an upstream source. Either complete (`missing: []`) or a hardware-level claim (`model_family: "*"`, `missing: ["model"]`).
- **`derived`** — A synthesized join across sources. Always declares what it lacks in `missing` (e.g., `["model"]` or `["hw"]`) and is flagged as a synthesized join in the UI and API.
- **`hand`** — Manually curated and verified by a contributor with a pointer URL and quote.

**`*` hardware rows:** When a source only claims that a runtime backend supports a hardware architecture (regardless of model), `model_family` is `"*"` and `missing` contains `"model"`. In model-specific queries, `*` rows are returned under `context` rather than `rows`, so they never masquerade as model-specific answers.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add a `solved` or `rejected` combination via a GitHub Issue or Pull Request.
