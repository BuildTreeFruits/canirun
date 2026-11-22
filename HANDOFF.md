# HANDOFF — solve.run combo index (built 2026-11-22, ~02:30 ET)

Written by the build lead at session stop. Everything here is what is actually on disk and
actually verified, plus what is broken. Read §1 and §2 first; they are the whole thing.

---

## 1. What exists now

A working local-inference **hardware × model × engine** index with a real website, a real JSON
API, a real corpus, and a vote/miss service. It is the v1 of the blueprint, not a slide deck.

```
python3 scripts/serve.py
#  site   http://127.0.0.1:8787/
#  docs   http://127.0.0.1:8787/api/docs      ← the agent integration paragraph
```

A server may already be running on port 8787 (started by the lead before stopping). If it is,
just open the URL. If not, run the command above.

| part | where | state |
|---|---|---|
| Corpus | `data/rows/*.jsonl`, `data/combos.json`, `data/export.jsonl` | **116 rows** (104 solved, 12 rejected, 0 wanted), 8 vendors, 30 model families, 4 runtimes |
| Contract | `CONTRACT.md` | frozen, has been amended twice, **read it before changing shape** |
| Scrapers | `scrapers/sources/` (5 sources), `scrapers/run_all.py` | live, re-runnable, cached |
| Pipeline | `pipeline/` (`build.py`, `schema.py`, `normalize.py`, `votes.py`, `export.py`, `check_links.py`) | 32/32 tests pass, idempotent |
| Website | `web/` (`index.html`, `js/`, `css/`) | no framework, no build step, works from `file://` |
| API | `api/server.py` + friends, `scripts/serve.py` | 57 tests pass (1 skipped), all routes verified |
| Agent docs | `api/AGENT.md`, `/api/docs` | paste-ready prompt snippet |

### Verified working (lead-verified by hand, not just reported)

- `GET /api/lookup?hw=sm_90` → hits, mixed solved + rejected rows.
- `GET /api/lookup?hw=sm_86&model=qwen3` → `is_miss: true`, `reason: "partial-context"`,
  `counts.context: 1`, and the sm_86 hardware claim attached as context — **this is the product's
  central behaviour and it works at the API layer.**
- `POST /api/want/{id}` twice with the same voter → `want_votes: 1` (idempotent).
- `POST /api/miss` × 3 distinct searchers → a provisional `wanted` row appears and the lookup
  flips from miss to hit.
- `data/export.jsonl` → `ETag` + `304` on `If-None-Match`.
- `python3 pipeline/build.py --check` → second run byte-identical except `generated_at`.
- `POST /api/want/.../llama.cpp` and `.../llama_cpp` → same id, `want_votes` stays 1 (no double count);
  unknown runtime → `400 unknown-runtime`; `?runtime=llama.cpp` reads a `llama_cpp` row.
- `GET /api/lookup?q=nonexistentword` → `no-match`, 0 votes.
- Miss panel rendered in headless Chrome and read back: says "No claim on record for …",
  shows the dataset date, "this is a recorded gap, not a broken page", counters, Want button,
  copyable JSON. It passes the blueprint's deciding test.

## 2. Corpus honesty (the thing to not break)

**No upstream publishes a hardware × model × runtime capability matrix.** They publish backend
build docs and package compatibility tables. So the corpus is two honest kinds of row:

- `scraped` (80) — the upstream doc explicitly names the hardware for that backend. Real claim.
- `derived` (36) — a synthesised join. Every one carries `missing: ["model"]` (or `["model","hw"]`),
  saying exactly which dimension is not quoted. Shown in the UI as "synthesised join — may be wrong".

74–76 rows are `model_family: "*"` = hardware-level claims ("this backend supports this card"),
which is **not** the same as answering a model-specific query. The API/UI treat `*` rows as
`context`, never as an answer. Do not let anything collapse that distinction.

Remaining known gap: **no model-specific rows at all.** The HF scrapers emit model×runtime
artifact rows (`missing: ["hw"]`), and the backend scrapers emit hardware×runtime rows — the join
between them is deliberately not fabricated. That join is the single most valuable next piece of
work, and it is also the one most likely to produce wrong rows. If you build it, add
`source_kind: "derived"` + keep `missing` truthful.

## 3. Decisions taken that the blueprint left open

- **Wanted list in v1: yes.** It is the miss half of the product.
- **Vote identity: anonymous device key**, not GitHub login (blueprint recommended GitHub).
  Reasoning: a login wall is a decision cost, and the habit dies on decision cost. Revisit only if
  spam appears.
- **Miss log auto-creates wanted rows at 3 distinct searchers**, `provisional: true`.
- **No MCP server.** O's call: "mcp tool is too much for this". HTTP + prompt snippet instead.
- **Vote on an id with no stored row materialises a stored row** (pipeline writes it, not the
  serving layer) — otherwise the write path and the export disagree about what exists.
- Scope stays local inference; the schema (`arm-cpu`, `x86-cpu`) still generalises.

## 4. CONTRACT amendments made mid-build (why the contract has two "corrections" in it)

1. **Ids are dot-free.** Original §2 contradicted itself. Final rule: lowercase, every `.` →
   `_`, `_` and `-` pass through untouched. `llama.cpp` → `llama_cpp` in the id, field keeps dots.
   `mlx-lm` stays `mlx-lm`. Ids are permanent (vote key + deep link), so this mattered.
2. **Invariant 2 relaxed** (the API agent caught this): `scraped` rows may carry `missing: ["model"]`
   when `model_family == "*"`. The old rule made every scraped hardware claim invalid by
   construction, which would have forced honest rows to masquerade as `derived`. New invariant 9
   requires `*` rows to declare `"model"` in `missing`.

## 5. Known-broken / unfinished — read before you trust the site

Ordered by how much it matters.

1. ~~Website `*`-context counters wrong~~ — **FIXED and verified by lead before stop.**
   `web/js/lookup.js` was applying the status filter to `*` rows and deriving counters from a
   filtered pool. Now matches `api/store.py`. Verified live:
   `#lookup?hw=sm_86&model=qwen3` → "HARDWARE-LEVEL CLAIMS 1", reason `partial-context`, honest
   hint ("Hardware-level support exists for llama.cpp; no model-specific claim"). `#lookup?hw=sm_86`
   is a real hit, not a miss. A 32-query differential test between JS and Python now agrees.
   **If page and API ever disagree, run `curl 'http://127.0.0.1:8787/api/lookup?...' | jq .miss`.**
   Frontend's own caveat: context counts use `max(API count, attached rows)` so the page can never
   contradict its own sentence — the API is still authoritative.
2. **Wanted state is empty by design right now.** The lead removed every synthetic vote and
   miss-created test row before stopping (the site should not open showing fake demand). So
   `by_status` is `solved: 104, rejected: 12, wanted: 0`. Vote once in the UI and the wanted state
   appears. Note: `web/js/lookup.js` converts ES modules to classic scripts so the page works when
   double-clicked (`file://`) — a deliberate tradeoff, one copy of code, zero build step. The seed helper is `python3 pipeline/build.py --demo`
   (writes synthetic votes to a separate `data/demo.votes.json`, never to real `data/votes.json`).
3. **gh_issues and gh_releases are thin** (13 and 1 rows). The brief wanted ~60 issue-derived
   rows; GitHub's unauthenticated search API rate-limited the run. Not a lie in the data, just a
   missing source. Retrying with a token would help.
4. **No model-specific rows** (see §2). The corpus answers "does this card have a backend?"
   much better than "does this card run model X?".
5. **Learned the hard way at stop: restart the server after backing-end edits.** A stale
   `scripts/serve.py` process (started before the fixed `api/views.py` was written) made two
   already-fixed bugs look live. If something seems broken, check
   `ps -o lstart -p $(lsof -ti:8787 -sTCP:LISTEN)` against `stat -f %Sm api/*.py` before debugging code.
6. **`web/snapshot.js` is a stale-able offline snapshot**, regenerated by
   `node web/tools/inline-snapshot.mjs`. It is what shows when you double-click `web/index.html`
   with no server. It goes stale whenever the corpus changes — rerun that command after any
   rebuild, or just use `scripts/serve.py`.
7. **The real corpus has no model-specific `rejected` row**, so the "rejected" starter only shows
   on the sample dataset (footer → "View the sample dataset"). Not a bug, a corpus gap.
8. **`data/taxonomy.extensions.json` was mislabeling model "vendor".** The scraper wrote the HF
   *uploader* (unsloth, bartowski, handy-computer) into `vendor`, which means "who uploaded the
   quant", not who made the model. Lead fixed it: `vendor` = model author (from `data/taxonomy.json`),
   `hf_uploader` = uploader. It never reached a row (rows carry no model vendor), so the export was
   unaffected — but do not reintroduce it if you add a model/author column.
9. **`pipeline/votes.py` materialised vote rows with a dot-free `runtime` field** (`llama_cpp`
   instead of `llama.cpp`). Lead fixed it with `_canonical_runtime_slug()` mapping the id segment
   back through the taxonomy; unknown segments pass through verbatim rather than guessing.
10. `data/votes.json` and `data/misses.jsonl` are the only irreplaceable files. The API writes them
   by atomic rename under a lock. Back them up if you care.

## 6. Exactly where to start next session

In order:

1. `python3 scripts/serve.py`, open `#lookup?hw=sm_86&model=qwen3` — should show
   "HARDWARE-LEVEL CLAIMS 1" and `partial-context`. Spot-check against
   `curl 'http://127.0.0.1:8787/api/lookup?hw=sm_86&model=qwen3' | jq .miss`.
2. ~~git commit~~ — **DONE.** `f592320` contains the whole v1 (89 files). `git log` to see it.
   Commit after every rebuild that changes `data/`; that is the durability story.
3. Build the real **model × hardware join** (the actual product value) — start with one narrow,
   verifiable slice: for 5 popular model families, resolve which quant artifacts exist (HF rows
   already have `model_rev` + quant filenames+bytes), and emit `derived` rows that say
   `missing: []` **only** where an upstream doc or issue actually links that model to that card.
   Everything else stays `partial`.
4. Retry `scrapers/sources/gh_issues.py` with a `GITHUB_TOKEN` (it takes the env var if you add
   one) — issue titles are where "works on my card" claims actually live, which is exactly the
   row type this index was built to collect.
5. Hosting, when you have a domain: `api/Caddyfile` + `api/systemd/solve-run.service` +
   `api/DEPLOY.md` are written and honest (no claimed live host). Remember O's standing rule:
   **no bulk domain lookups.**

## 7. Re-running the data pipeline

```bash
python3 scrapers/run_all.py          # re-scrape (polite: 1 req/s, cached, offline-safe)
python3 pipeline/build.py            # validate + merge + export  → data/combos.json
python3 pipeline/build.py --check    # prove idempotency
python3 pipeline/check_links.py      # pointer_alive health (HEAD/GET, 7-day cache)
python3 pipeline/tests/test_pipeline.py
python3 api/tests/test_api.py            # 63 tests
node web/tools/inline-snapshot.mjs   # regenerate the file:// offline snapshot
```

Pipeline order matters: scrapers write `scrapers/out/*.jsonl`, never `data/rows/`.
Rows are never deleted by a scraper or a rebuild — deletion is a human act (the lead removed 3
synthetic rows by hand in this session; that is the intended procedure).

## 8. How this was built

Four agents in parallel against a frozen `CONTRACT.md` written up front: **scraper** (5 live
sources), **pipeline** (validate/merge/export), **frontend** (the site), **api** (service + agent
docs). Write scopes were disjoint per agent. The contract caught real drift three times
(dotted ids, invariant 2, vote-id runtime slugs) which is the argument for writing it first.

Design texts, if you need the original reasoning:
- `00 My Notes/Kernel index — hardware × model × engine.md`
- `40 Reference/App Docs/Agent Builds/Loom/blueprints/local-inference-solutions-index.md`
