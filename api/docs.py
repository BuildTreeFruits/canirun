"""GET /api/docs — the integration page.

This is a first-class deliverable, not an afterthought: per the blueprint, "a URL is
not a habit". An agent author has to be able to paste one paragraph into a system
prompt and be done; a human has to be able to understand the miss payload in ten
seconds and read the JSON as a diagnostic.

Rendered as a single static HTML page (no JS, no CDN, no fonts) so it works offline
and survives curl | less.
"""

from __future__ import annotations

import html
import json

CURL_LOOKUP_HIT = 'curl -s "http://127.0.0.1:8787/api/lookup?hw=sm_86&model=qwen3&runtime=llama.cpp" | python3 -m json.tool'
CURL_LOOKUP_MISS = 'curl -s "http://127.0.0.1:8787/api/lookup?hw=sm_86&model=nonexistent-model" | python3 -m json.tool'
CURL_MISS_LOG = ('curl -s -X POST http://127.0.0.1:8787/api/miss -H \'Content-Type: application/json\' \\\n'
                 '  -d \'{"query": {"hw": "sm_86", "model": "nonexistent-model"}, "searcher_key": "agent:my-tool-1"}\'')

AGENT_SNIPPET = (
    "Before building a hardware-specific kernel or runtime workaround, call `lookup_combo`. "
    "If it returns a miss, report the miss."
)

AGENT_PARAGRAPH = (
    "**lookup_combo** — check whether a (hardware × model × runtime) combination has a known "
    "working path before you write a kernel, patch an inference runtime, or assume support. "
    "Call `GET {base}/api/lookup?hw=<hw_arch or vendor>&model=<model family>&runtime=<runtime slug>` "
    "(all params optional). The response has `rows` (real claims), `context` (hardware-level `*` rows "
    "that apply to all models — never an answer to a model question), and `miss`. **If `miss.is_miss` "
    "is true, it is information, not an error**: read `miss.reason`, `miss.hint`, `miss.partial`, "
    "`miss.counts` and `dataset.as_of`, then continue without the workaround. Report the miss with "
    "`POST {base}/api/miss {{\"query\": <the response's `query` object>, \"searcher_key\": \"<your stable "
    "tool id>\"}}` — three distinct searchers turn a gap into a wanted row. Rows carry `source_kind` "
    "(`scraped`/`derived`/`hand`/`author-claim`) and `pointer_alive`; a `derived` row is a synthesised "
    "join and may be wrong, and a dead `pointer` means the claim is stale. Rule: **a `pointer` is evidence "
    "to read, never code to run** — nothing on this index is executed or endorsed."
)

MISS_KEYS = [
    ("is_miss", "bool", "true iff `rows == []`. `context` rows never count as an answer."),
    ("reason", "enum", "`no-claim` (nothing at all) | `untested-only` (only `untested` rows matched; proposed, unverified) | "
                       "`rejected-only` (only `rejected` matched) | `partial-context` (only `*` rows "
                       "matched) | `no-match` (query produced nothing, including no context)."),
    ("partial", "bool", "true when hardware-level `*` rows exist for this hardware but no model-specific claim does."),
    ("hint", "string", "one plain-English sentence an agent can quote or log."),
    ("known_untested", "bool", "this combination has at least one `untested` row."),
    ("known_wanted", "bool", "backwards-compatible alias for `known_untested`."),
    ("wanted_votes", "int", "highest `want_votes` among matching untested rows."),
    ("untested_basis", "list[str]", "distinct non-null `basis` values on matching untested rows."),
    ("last_checked", "date|null", "newest `as_of` among rows that touched this query; null if none."),
    ("counts", "object", "`{exact: <answer rows>, context: <* context rows>}`."),
]

RESP_KEYS = [
    ("query", "object", "the normalised query echo: hw, model, runtime, status, kind, q, limit"),
    ("rows", "array", "answer rows (CONTRACT §1 shape)"),
    ("context", "array", "`model_family: \"*\"` rows — hardware-level support, applies to all models"),
    ("miss", "object", "always present; `{\"is_miss\": false}` on a hit, the full §4 object on a miss"),
    ("query_id", "string", "8-hex, deterministic for a given query — use it to correlate miss reports"),
    ("generated_at", "string", "ISO-8601 UTC of this response"),
    ("dataset", "object", "`{rows, as_of, version}` — always show as_of; a stale date is information"),
]

CSS = """
:root{--bg:#0f1115;--fg:#e7e9ee;--mut:#9aa3b2;--line:#262b36;--acc:#7cc4ff;--warn:#ffcf6b;--ok:#6ee7a8;--bad:#ff8a8a;--code:#12151c}
@media (prefers-color-scheme: light){:root{--bg:#fbfbfd;--fg:#16181d;--mut:#5a6270;--line:#e3e6ec;--acc:#0b6bcb;--warn:#8a5b00;--ok:#0a7d4b;--bad:#b3261e;--code:#f2f4f8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:60rem;margin:0 auto;padding:2rem 1.25rem 5rem}
h1{font-size:1.6rem;margin:0 0 .25rem}
h2{font-size:1.15rem;margin:2.25rem 0 .6rem;padding-bottom:.3rem;border-bottom:1px solid var(--line)}
h3{font-size:.98rem;margin:1.4rem 0 .4rem}
p,li{color:var(--fg)}
.sub{color:var(--mut);margin:0 0 1.5rem}
code,pre,kbd{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.875em}
code{background:var(--code);padding:.1em .35em;border-radius:4px}
pre{background:var(--code);border:1px solid var(--line);border-radius:8px;padding:.9rem 1rem;overflow:auto}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem;font-size:.92rem}
th,td{text-align:left;vertical-align:top;padding:.4rem .55rem;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600}
.paste{border-left:3px solid var(--acc);background:var(--code);padding:.9rem 1rem;border-radius:0 8px 8px 0}
.paste pre{background:none;border:0;padding:0;margin:.5rem 0 0}
.tag{display:inline-block;font-size:.72rem;letter-spacing:.04em;text-transform:uppercase;border:1px solid var(--line);border-radius:999px;padding:.05rem .5rem;color:var(--mut);margin-right:.35rem}
.get{color:var(--ok)} .post{color:var(--acc)} .del{color:var(--bad)}
.note{color:var(--mut);font-size:.9rem}
a{color:var(--acc)}
nav.toc{display:flex;flex-wrap:wrap;gap:.4rem .9rem;font-size:.9rem;margin:0 0 1rem}
"""


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def render_html(store, base_url: str = "http://127.0.0.1:8787") -> str:
    ds = store.dataset()
    meta = ds.meta()
    base = base_url.rstrip("/")
    example_query = {"hw": "sm_86", "model": "qwen3", "runtime": None, "status": None,
                     "kind": None, "q": None, "limit": 50}
    example_miss = {
        "is_miss": True, "reason": "no-claim", "partial": False,
        "hint": "No claim on record for sm_86 × qwen3. Hardware-level support exists for llama.cpp; no model-specific claim.",
        "known_wanted": False, "wanted_votes": 0, "last_checked": None,
        "counts": {"exact": 0, "context": 2},
    }
    example_resp = {
        "query": example_query, "rows": [], "context": [], "miss": example_miss,
        "query_id": "ab12cd34", "generated_at": "2026-11-22T06:12:00Z",
        "dataset": {"rows": meta.get("rows", 0), "as_of": meta.get("as_of"),
                    "version": meta.get("version")},
    }

    miss_rows = "\n".join(
        f"<tr><td><code>{_esc(k)}</code></td><td><code>{_esc(t)}</code></td><td>{_esc(d)}</td></tr>"
        for k, t, d in MISS_KEYS)
    resp_rows = "\n".join(
        f"<tr><td><code>{_esc(k)}</code></td><td><code>{_esc(t)}</code></td><td>{_esc(d)}</td></tr>"
        for k, t, d in RESP_KEYS)

    routes = [
        ("GET", "/api/lookup", "CONTRACT §4 query → rows + context + miss. Side-effect free "
                                "(add <code>&amp;log=1</code> to log the miss)."),
        ("GET", "/api/rows", "Browse with filters + counts (status, hw, model, runtime, kind, q, limit, offset)."),
        ("GET", "/api/wanted", "Untested / wanted rows: votes desc, then want_first asc."),
        ("GET", "/api/untested", "Alias of <code>/api/wanted</code>."),
        ("GET", "/llms.txt", "Plain-text summary for LLMs (<code>text/plain; charset=utf-8</code>)."),
        ("POST", "/api/want/{id}", 'Body <code>{"voter": "gh:you"}</code>. Idempotent per (id, voter).'),
        ("DELETE", "/api/want/{id}", "Retract a vote. Same body."),
        ("POST", "/api/miss", 'Body <code>{"query": {...}, "searcher_key": "..."}</code>. 3 distinct searchers → wanted row.'),
        ("GET", "/api/combos.json", "The export. ETag + Cache-Control; 304 on If-None-Match."),
        ("GET", "/api/export.jsonl", "Full JSONL dump. ETag + Cache-Control; 304 on If-None-Match."),
        ("GET", "/api/taxonomy", "Vendors / runtimes / models / hw_archs for dropdowns."),
        ("GET", "/api/health", "Liveness, dataset freshness, write-path counters."),
        ("GET", "/api/openapi.json", "Machine-readable OpenAPI 3.1."),
    ]
    route_rows = "\n".join(
        f'<tr><td><span class="{m.lower() if m != "DELETE" else "del"}">{m}</span></td>'
        f"<td><code>{_esc(p)}</code></td><td>{d}</td></tr>" for m, p, d in routes)

    ds_line = f'{meta.get("rows")} rows · as_of {meta.get("as_of")} · version {meta.get("version")}'
    err = (f'<p class="note" style="color:var(--warn)">⚠ dataset: {_esc(ds.error)}</p>'
           if ds.error else "")

    snippet_para = AGENT_PARAGRAPH.format(base=base)

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>canirun combo index — API</title>
<style>{CSS}</style>
</head><body><main>
<h1>canirun combo index — API</h1>
<p class="sub">Local-inference combination index. {_esc(ds_line)}. Standard library only; the export is a plain file at a stable URL.</p>
{err}
<nav class="toc">
  <a href="#agent">For agents</a> <a href="#lookup">/api/lookup</a> <a href="#miss">The miss payload</a>
  <a href="#write">Votes &amp; miss reports</a> <a href="#export">Export &amp; 304</a> <a href="#routes">All routes</a>
  <a href="#curl">curl cookbook</a> <a href="/api/openapi.json">openapi.json</a>
</nav>

<h2 id="agent">For agents</h2>
<p>Add this snippet to a system prompt or agent config:</p>
<div class="paste"><strong>Instruction snippet</strong><pre><code>{_esc(AGENT_SNIPPET)}</code></pre></div>

<h3>Tool description</h3>
<div class="paste"><pre><code>{_esc(snippet_para)}</code></pre></div>
<p class="note">Wrap <code>GET /api/lookup</code> and <code>POST /api/miss</code> if your agent needs a tool.</p>

<h2 id="lookup">GET /api/lookup</h2>
<p>All params optional, unknown params ignored. Matching: <code>hw</code> matches <code>hw_arch</code>
exactly, else <code>hw_vendor</code>, else prefix; <code>model</code> matches <code>model_family</code>
exactly, else contains (<code>*</code> rows are <em>context only</em>); <code>runtime</code> matches slug
in <em>either spelling</em> — <code>llama.cpp</code> and <code>llama_cpp</code> are the same runtime — then
display name; <code>limit</code> defaults to 50, max 500.</p>
<p class="note"><strong>Why two spellings.</strong> Row ids may not contain dots (CONTRACT §2), so the id
segment for llama.cpp is <code>llama_cpp</code>. A row created by a vote carries the id segment in its
<code>runtime</code> field until the pipeline re-materialises it, so both forms are accepted everywhere.
<code>/api/taxonomy</code> publishes the mapping as <code>runtime_id_aliases</code>.</p>
<p class="note"><strong>Ids for voting.</strong> <code>POST /api/want/{id}</code> validates the id with the
pipeline's own rules and rejects non-canonical ids with a <code>400</code> plus <code>did_you_mean</code> —
send the canonical form (<code>nvidia/sm_86/qwen3/llama_cpp</code>, not <code>.../llama.cpp</code>).</p>
<table><tr><th>key</th><th>type</th><th>meaning</th></tr>
{resp_rows}
</table>
<p><code>miss</code> is always present; on a hit it is <code>{{"is_miss": false}}</code>.</p>

<h2 id="miss">The miss payload</h2>
<p>Returned when no model-specific rows match.</p>
<table><tr><th>key</th><th>type</th><th>meaning</th></tr>
{miss_rows}
</table>
<h3>Example: the combination does not exist</h3>
<pre><code>{_esc(json.dumps(example_resp, indent=2))}</code></pre>
<p class="note">Read it as: <em>"As of {_esc(meta.get('as_of') or 'the dataset date')}, nobody has recorded a claim for
sm_86 × qwen3. llama.cpp is known to support the card (2 hardware-level rows), but that is not a
statement that qwen3 runs on it."</em> A specific-model query against a card with only <code>*</code> rows
returns <code>reason: "partial-context"</code>, <code>partial: true</code> and the <code>*</code> rows in
<code>context</code>.</p>

<h2 id="write">Votes and miss reports</h2>
<h3>POST /api/want/{{id}} — idempotent per voter</h3>
<pre><code>curl -s -X POST {_esc(base)}/api/want/nvidia/sm_120/deepseek-v4/llama.cpp \\
  -H 'Content-Type: application/json' \\
  -d '{{"voter": "gh:yourhandle"}}'
# → {{"id": "nvidia/sm_120/deepseek-v4/llama.cpp", "want_votes": 1, "want_first": "2026-11-22", "voted": true}}
# repeat the same call → same want_votes. Different voter → +1. DELETE retracts.</code></pre>
<p class="note">Rate limit: 20 writes/min per IP. The count is the size of the requester set, so a
double-click cannot inflate a row. A vote works even for an id the pipeline has not exported yet —
that is what makes the "want this" button on a miss panel useful.</p>

<h3>POST /api/miss — how the wanted list fills itself</h3>
<pre><code>{_esc(CURL_MISS_LOG)}
# → {{"logged": true, "query_id": "<8-hex>", "distinct_searchers": 1, "creates_wanted_at": 3}}</code></pre>
<p>Each miss appends one line to the miss log: <code>{{ts, query, query_id, searcher_key, user_agent}}</code>.
At <strong>3 distinct searchers</strong> on the same <code>query_id</code> the combination is auto-created as a
provisional <code>wanted</code> row (pipeline fold). A <code>GET /api/lookup?...&amp;log=1</code> logs the same
thing without a second round trip; plain GET never writes, because agents poll.</p>

<h2 id="export">The export, ETag and 304</h2>
<p><code>/api/combos.json</code> and <code>/api/export.jsonl</code> are the whole dataset. They are
byte-stable for unchanged input and serve <code>ETag</code> + <code>Cache-Control: {_esc("public, max-age=3600")}</code>,
so a mirror gets a <code>304 Not Modified</code> and no body:</p>
<pre><code>ETAG=$(curl -sI {_esc(base)}/api/export.jsonl | awk -F': ' 'tolower($1)=="etag"{{print $2}}' | tr -d '\\r')
curl -s -o /dev/null -w '%{{http_code}}\\n' -H "If-None-Match: $ETAG" {_esc(base)}/api/export.jsonl
# → 304</code></pre>
<p class="note">The export is also a plain file on disk (<code>data/export.jsonl</code>), which is the
fallback that keeps reads working if this service dies.</p>
<h3>What is inside <code>combos.json</code></h3>
<table><tr><th>key</th><th>meaning</th></tr>
<tr><td><code>version</code></td><td><code>"YYYY-MM-DD.N"</code> — bumps only when the content changes, so it is safe to poll</td></tr>
<tr><td><code>generated_at</code></td><td>the only volatile field; ignore it when diffing two builds</td></tr>
<tr><td><code>as_of</code></td><td>the date the corpus speaks for — always show this next to an answer</td></tr>
<tr><td><code>content_hash</code></td><td>hash of the row content, excluding <code>generated_at</code></td></tr>
<tr><td><code>counts</code></td><td>by_status, by_vendor, by_runtime, by_source_kind, by_hw_arch, by_model_family, by_created_by</td></tr>
<tr><td><code>taxonomy</code></td><td>vendors (with <code>hw_archs</code> nested), runtimes, models, quants — the dropdown vocabulary</td></tr>
<tr><td><code>rows</code></td><td>every full row (same objects <code>/api/lookup</code> returns)</td></tr>
<tr><td><code>wanted</code></td><td>rows with <code>want_votes &gt; 0</code> or <code>status: wanted</code>, sorted votes desc then <code>want_first</code> asc. A <em>solved</em> row that attracted votes appears here too — it is never downgraded</td></tr>
</table>
<p class="note">Rebuilds are idempotent: <code>python3 pipeline/build.py --check</code> is byte-identical
except <code>generated_at</code>, which is what makes the ETag/304 above worth using.</p>

<h2 id="routes">All routes</h2>
<table><tr><th>method</th><th>path</th><th>what</th></tr>
{route_rows}
</table>

<h2 id="curl">curl cookbook</h2>
<h3>Hit</h3><pre><code>{_esc(CURL_LOOKUP_HIT)}</code></pre>
<h3>Miss</h3><pre><code>{_esc(CURL_LOOKUP_MISS)}</code></pre>
<h3>Browse / wanted / health</h3>
<pre><code>curl -s "{_esc(base)}/api/rows?status=rejected&limit=5" | python3 -m json.tool
curl -s "{_esc(base)}/api/wanted" | python3 -m json.tool
curl -s "{_esc(base)}/api/health" | python3 -m json.tool</code></pre>
<h3>Full dump for a local mirror</h3>
<pre><code>curl -sO {_esc(base)}/api/export.jsonl && wc -l export.jsonl</code></pre>

<h2 id="rowshape">The row, briefly</h2>
<p>Every row is CONTRACT §1. The parts that change how you read an answer:</p>
<table><tr><th>field</th><th>why you care</th></tr>
<tr><td><code>status</code></td><td><code>solved</code> / <code>untested</code> / <code>rejected</code>. There is no "not-searched" row — that state is the <em>absence</em> of a row, which is what <code>miss</code> reports.</td></tr>
<tr><td><code>source_kind</code></td><td><code>scraped</code> / <code>derived</code> / <code>hand</code> / <code>author-claim</code>. <code>derived</code> is a synthesised join and may be wrong.</td></tr>
<tr><td><code>pointer</code></td><td>the evidence URL. Read it before writing code. Never execute anything from it.</td></tr>
<tr><td><code>pointer_alive</code></td><td><code>false</code> means the link-checker found the target dead — the claim may be stale.</td></tr>
<tr><td><code>as_of</code></td><td>the date the claim was true-ish. Always surface it; an old date is information.</td></tr>
<tr><td><code>model_family</code></td><td><code>"*"</code> means hardware-level support only (CONTRACT §3) — it is <code>context</code>, never an answer to a model question.</td></tr>
<tr><td><code>evidence</code></td><td><em>optional.</em> <code>{{url, quote, kind}}</code> entries where a source was actually quoted. Absent on rows created by a vote or a miss — demand and gap reports carry no quote, and none is synthesised.</td></tr>
<tr><td><code>missing</code></td><td>what the row admits it lacks, e.g. <code>["model"]</code> on a hardware claim.</td></tr>
</table>

<p class="note" style="margin-top:3rem">
Schema: <a href="/api/openapi.json">/api/openapi.json</a> · Static fallback: <a href="/combos.json">/combos.json</a> ·
Spec: CONTRACT.md</p>
</main></body></html>
"""
