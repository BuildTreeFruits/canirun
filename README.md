# solve.run — the combo list (v1 build)

A single canonical pointer for **hardware × model × engine** combinations in local LLM inference.
Built 2026-11-22 from:

- idea: `00 My Notes / Kernel index — hardware × model × engine.md`
- spec: `40 Reference/App Docs/Agent Builds/Loom/blueprints/local-inference-solutions-index.md`

The question it answers: *"Does a working solution exist for this card × this model × this engine,
and if not, is that a recorded gap or has nobody looked?"*

## Run it

```bash
python3 scripts/serve.py          # http://127.0.0.1:8787  (site)  /api/docs (agent docs)
python3 pipeline/build.py         # rebuild data/combos.json + data/rows/*.jsonl
python3 scrapers/run_all.py       # re-scrape upstreams (polite: 1 req/s, cached)
```

The site also works with no server at all — open `web/index.html` and it falls back to reading
`data/combos.json`. The API is what makes the want button and the miss log real.

## What is actually built

| piece | file | state |
|---|---|---|
| Frozen row contract | `CONTRACT.md` | written by lead, enforced by `pipeline/schema.py` |
| Scrapers (5 live sources) | `scrapers/sources/` | see `scrapers/README.md` for per-source yield |
| Normalizer + export | `pipeline/`, `data/combos.json`, `data/export.jsonl` | idempotent, no row deletion |
| Website | `web/` | search, four states, miss panel, want button, browse |
| API | `api/server.py` | `/api/lookup`, `/api/want/{id}`, `/api/miss`, `/api/export.jsonl` |
| Agent docs | `api/AGENT.md`, `/api/docs` | paste-ready prompt snippet |

## The four states, and the one line that decides whether this worked

| state | meaning | stored? |
|---|---|---|
| `solved` | a working path exists and is pointed to | yes, with `as_of` |
| `wanted` | someone looked, nothing found, ≥1 person wants it | yes, with votes + first-wanted date |
| `rejected` | tried, does not work on this card | yes, with the reason — this is free dedup |
| `not-searched` | nobody has claimed anything | **no** — absence of a row *is* the state |

> **Test:** open the site, search a combination that does not exist, and see it say so plainly
> with a date. If the empty answer feels like information, the product is real.
> If it feels like a broken page, nothing else matters.

## Honest limitation, flagged in the data itself

No upstream source publishes a hardware × model × runtime capability matrix. They publish
*backend build docs* and *package compatibility tables*. So most of the seed corpus is:

- **`scraped`** — the doc names this hardware for this runtime (a real claim, about hardware).
- **`derived`** — a synthesized join; `missing[]` states which dimension is asserted rather than
  quoted (`["model"]` = hardware-only claim, `["hw"]` = model-artifact-only claim).

`derived` rows are marked "synthesised join — may be wrong" everywhere they appear, and in the API
they never masquerade as scraped ones. The blueprint called this "a join is a guess wearing a
fact's clothes"; the `missing` field is how we keep the guess naked.

## Decisions taken lands-on-the-lead (the blueprint's open items)

- **Wanted list in v1: yes.** It is the miss half of the product; without it `not-searched` and
  `wanted` collapse into the same silence. Votes are one click, no form, idempotent per voter.
- **Vote write path: a tiny service**, not a PR. Confirms the blueprint's conclusion that the
  moment there is a want button there is a backend.
- **Vote identity: anonymous device key**, not GitHub login (blueprint's recommendation was
  GitHub). Reason: the product's whole thesis is that a habitual check must cost nothing; a
  login wall is the decision cost that kills the habit. `want_requesters` caps at 10 names for
  display and `want_votes` stays authoritative. Revisit if spam appears — the shape is ready.
- **Miss log auto-creates wanted rows at 3 distinct searchers**, `provisional: true`
  (the blueprint's own recommendation).
- **No MCP server in v1.** O's ruling: "mcp tool is too much for this — the agent is just
  searching for something." A stable HTTP JSON endpoint plus a pasteable prompt snippet is shipped
  instead.
- **Scope stays local inference.** The schema generalizes (`hw_vendor` has `arm-cpu`, `x86-cpu`);
  the seed data does not widen.

## Not built (deliberate)

Payments/escrow/bounties, benchmark re-runs, leaderboards, account system, domain purchase
(O's standing rule: no bulk domain lookups). The dataset is plain JSONL in git, so it outlives
the service — see blueprint §Failure modes #6.
