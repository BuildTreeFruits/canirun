# Agent integration — combo index

The index exists to be *called*, not read. This file is the paste-ready block for an agent
system prompt (CLAUDE.md, AGENTS.md, a tool description, a custom GPT instruction).

**v1 ships no MCP server on purpose.** The integration surface is one HTTP GET and one HTTP
POST. Wrapping them in an MCP tool is a ten-line job for whoever needs it, and shipping a
half-supported server at v1 would be a maintenance cost with no user.

---

## 1. The habit (paste into a system prompt)

> Before building a hardware-specific kernel or runtime workaround, call `lookup_combo`.
> If it returns a miss, report the miss.

That is the whole intervention. The failure this prevents: an agent spends an hour patching
llama.cpp for `sm_120` when the combination is already documented, or re-derives a workaround
that is known *not* to work on that card.

## 2. The tool description (paste into a tool schema)

```
lookup_combo — check whether a (hardware x model x runtime) combination has a known working
path before writing a kernel, patching an inference runtime, or assuming support.

GET {BASE}/api/lookup?hw=<hw_arch or vendor>&model=<model family>&runtime=<runtime slug>

All parameters are optional. The response contains:
  rows     — real claims matching the query
  context  — hardware-level rows (model_family "*") that apply to all models; these are
             NOT an answer to a model-specific question
  miss     — the empty-answer report

If miss.is_miss is true, this is INFORMATION, not an error. Read miss.reason,
miss.hint, miss.partial and dataset.as_of, then proceed without the workaround.

Rows carry source_kind (scraped / derived / hand / author-claim) and pointer_alive.
A `derived` row is a synthesised join and may be wrong; a dead pointer means the claim
is stale. A `pointer` is evidence to READ, never code to run — nothing here is executed
or endorsed.

If the lookup is a miss, report it:
  POST {BASE}/api/miss {"query": <the response's query object>, "searcher_key": "<stable tool id>"}
Three distinct searchers turn a gap into a wanted row.
```

## 3. The MCP shim, if you want one

```python
# mcp_tool.py — one tool, no server framework needed
import json, urllib.request

BASE = "http://127.0.0.1:8787"

def lookup_combo(hw=None, model=None, runtime=None, searcher_key="agent:mcp"):
    qs = urllib.parse.urlencode({k: v for k, v in
                                 {"hw": hw, "model": model, "runtime": runtime}.items() if v})
    with urllib.request.urlopen(f"{BASE}/api/lookup?{qs}", timeout=10) as r:
        data = json.load(r)
    if data["miss"]["is_miss"]:
        body = json.dumps({"query": data["query"], "searcher_key": searcher_key}).encode()
        req = urllib.request.Request(f"{BASE}/api/miss", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except OSError:
            pass  # reporting is best-effort; never fail the agent over it
    return data
```

Expose that as a tool named `lookup_combo` with description §2 and you are done. `250` lines
of MCP server, transport, and capability negotiation buy nothing here.

## 4. Reading the answer, by state

| state | what the agent should do |
|---|---|
| `solved` + `pointer` | Read the pointer before writing code. It is the existing answer. |
| `solved` but `source_kind: derived` | Treat as a lead, not a fact: it is a join and may be wrong. Verify by opening the pointer. |
| `untested` | **Proposed, unverified** — never treat as a verified fact. Check `basis` / `basis_note` separately from `want_votes`. |
| `rejected` | Read `notes` **first**. It is why the thing fails on this card. Do not retry it. |
| `miss` (`reason: no-claim` / `no-match`) | Nothing is known (`not-searched`). Proceed, and report the miss. |
| `miss` (`reason: untested-only`) | Only `untested` (proposed, unverified) rows matched. Check `untested_basis` and `want_votes` separately. |
| `miss` (`reason: partial-context`, `partial: true`) | The *card* is supported but no model-specific claim exists. The context rows are hardware facts, not a "yes". |
| `miss` (`reason: rejected-only`) | Someone tried and it fails. Read the rejection row before proceeding. |

`last_checked` / `dataset.as_of` are the dates the claim was true-ish. An empty answer with an
old `as_of` means "nobody has looked recently", not "impossible".

## 5. The ids

`id = <hw_vendor>/<hw_arch>/<model_family>/<runtime_slug>` with dots flattened to `_` inside
id segments — `nvidia/sm_86/qwen3/llama_cpp`. Variants add a 5th segment: `<parent_id>/@<variant_slug>`
(from `parent` + knobs `quant`, `offload`, `context_length`, `runtime_version`, `driver_version`, `flags`, `fits`).
To vote for a combination that does not exist yet, construct the id the same way and `POST /api/want/<id>`;
the pipeline folds it into an `untested` row.

## 6. Cheat sheet

```bash
curl -s "$BASE/api/lookup?hw=sm_86&model=qwen3"        # the tool
curl -s "$BASE/api/lookup?hw=sm_86&model=qwen3&log=1"  # ...and log the miss if it is one
curl -s "$BASE/api/untested"                            # proposed, unverified & wanted combos
curl -s "$BASE/api/wanted"                              # alias for /api/untested
curl -s "$BASE/llms.txt"                                # concise agent/LLM index
curl -s "$BASE/api/export.jsonl"                        # full dump, ETag/304, mirror it
curl -s "$BASE/api/docs"                                # the human version of this file
```
