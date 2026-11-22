/* render.js — classic script build (see web/tools/to-classic.mjs).
   Loaded in order from index.html so the site also works from file://,
   where browsers block ES modules and fetch(). Source of truth is this file. */
(function (SR) {
'use strict';
  // dependencies pulled from the shared namespace
  const { formatDate, formatDateShort, ageOf, ageLevel, domainOf, pathOf, isSafeHttp, plural, prettyJson, missSentence } = SR;

/**
 * render.js — HTML string builders. Pure: data in, markup out, no DOM access,
 * no event listeners. app.js wires behaviour onto the markup.
 *
 * All interpolated text goes through `esc()` (or `attr()`). Row content comes
 * from scrapers and from strangers on the internet, so it is treated as hostile:
 * every row string is escaped, every URL passes an http(s) check before it is
 * put in an href.
 */


/* ------------------------------------------------------------------ escape */

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
function esc(v) {
  return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, (c) => ESC[c]);
}
const attr = esc;

/** DOM-id-safe form of a row id (ids are slashes + dots; ids need neither). */
function cssId(s) {
  return String(s || '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

/** Hostile-input-safe href: http(s) only, else null. */
function safeHref(url) {
  return isSafeHttp(url) ? attr(String(url)) : null;
}

/* ------------------------------------------------------------------ labels */

const STATE_META = {
  solved: { label: 'Solved', glyph: '✓', word: 'has a known solution' },
  wanted: { label: 'Wanted', glyph: '↑', word: 'is wanted, not solved' },
  rejected: { label: 'Rejected', glyph: '✕', word: 'was tried and does not work' },
  context: { label: 'Hardware-level', glyph: '＊', word: 'says the backend supports this card' },
  miss: { label: 'Not searched', glyph: '∅', word: 'has no claim on record' }
};

const KIND_META = {
  scraped: { label: 'Scraped', note: 'pointing at someone else’s claim, as published upstream' },
  derived: { label: 'Derived', note: 'synthesised join — may be wrong' },
  hand: { label: 'Hand-entered', note: 'entered by a person' },
  'author-claim': { label: 'Author claim', note: 'the upstream author says so' }
};

const REASON_META = {
  'no-claim': {
    label: 'no claim on record',
    lead: 'Nobody has recorded this combination.'
  },
  'wanted-only': {
    label: 'wanted only',
    lead: 'People are asking for this combination. Nobody has recorded a working path yet.'
  },
  'rejected-only': {
    label: 'rejected only',
    lead: 'Someone tried this combination and it does not work on this card.'
  },
  'partial-context': {
    label: 'hardware-level only',
    lead: 'The backend claims support for this card, but no claim names this model.'
  },
  'no-match': {
    label: 'nothing matches',
    lead: 'Nothing in the dataset matches this query — not even a hardware-level claim.'
  }
};

/* --------------------------------------------------------------- fragments */

function stateChip(state, { small = false } = {}) {
  const m = STATE_META[state] || STATE_META.miss;
  return `<span class="state-chip"${small ? ' style="font-size:0.72rem"' : ''}>
    <span class="glyph" aria-hidden="true">${m.glyph}</span>${esc(m.label)}</span>`;
}

function kindBadge(kind) {
  const m = KIND_META[kind];
  if (!m) return '';
  return `<span class="badge badge-kind" data-kind="${attr(kind)}" title="${attr(m.note)}">
    <span aria-hidden="true">◈</span>${esc(m.label)}</span>`;
}

/** The "derived is a guess wearing a fact's clothes" warning — must never be subtle. */
function derivedNote(kind) {
  if (kind !== 'derived') return '';
  return `<span class="badge badge-kind" data-kind="derived" title="This row was produced by joining two sources. Nobody has run this exact combination.">
    <span aria-hidden="true">≈</span>Synthesised join — may be wrong</span>`;
}

function provenanceBadges(row) {
  const out = [];
  if (row.pointer_alive === false) {
    out.push(
      `<span class="badge badge-dead" title="The link checker could not reach this pointer. The claim is kept, not deleted.">
        <span aria-hidden="true">●</span>Pointer may be dead</span>`
    );
  }
  if (row.provisional) {
    out.push(`<span class="badge badge-provisional" title="Created automatically from searches that found nothing. Nobody has confirmed it.">Provisional</span>`);
  }
  return out.join('');
}

/** The combination as a sentence-ish title: sm_86 × qwen3 × llama.cpp */
function comboTitle(row) {
  const parts = [row.hw_arch, row.model_family, row.runtime].map(String);
  const html = parts
    .map((p) => `<span class="part">${esc(p)}</span>`)
    .join('<span class="sep" aria-hidden="true"> × </span>');
  return html;
}

function hwLine(row) {
  const vendor = row.hw_vendor ? `${esc(row.hw_vendor)} / ${esc(row.hw_arch)}` : esc(row.hw_arch || '');
  const name = row.hw_name ? ` <span class="hw-name">· ${esc(row.hw_name)}</span>` : '';
  return `${vendor}${name}`;
}

function missingFact(row) {
  const missing = Array.isArray(row.missing) ? row.missing : [];
  if (!missing.length) return '';
  return `<div class="kv kv-missing"><dt>Stated as missing</dt><dd>${esc(missing.join(', '))}</dd></div>`;
}

function measurementFact(row) {
  const m = row.measurement;
  if (!m || typeof m !== 'object') return '';
  const tok = typeof m.tok_s === 'number' ? `${m.tok_s} tok/s` : null;
  if (!tok) return '';
  return `<div class="kv"><dt>Measured</dt><dd>${esc(tok)}${m.source ? ` <small>${esc(m.source)}</small>` : ''}</dd></div>`;
}

function quantFact(row) {
  if (!row.quant) return '';
  return `<div class="kv"><dt>Quant</dt><dd><code>${esc(row.quant)}</code></dd></div>`;
}

function revFact(row) {
  if (!row.runtime_rev) return '';
  return `<div class="kv"><dt>Runtime pinned</dt><dd><code>${esc(row.runtime_rev)}</code></dd></div>`;
}

function modelRevFact(row) {
  if (!row.model_rev) return '';
  return `<div class="kv"><dt>Model rev</dt><dd><code>${esc(row.model_rev)}</code></dd></div>`;
}

/* ----------------------------------------------------------------- pointer */

/**
 * Pointer block: host first as plain, non-clickable text, then the link that
 * carries the path. This ordering is the whole point — you read and judge the
 * host *before* the link invites a click (CONTRACT failure mode 5). Dead
 * pointers keep the row but are demoted and labelled, never hidden.
 */
function pointerBlock(row) {
  const dead = row.pointer_alive === false;
  const href = safeHref(row.pointer);
  if (!href) {
    if (row.status === 'rejected') return '';
    return `<div class="pointer pointer-dead">
      <div class="pointer-label">No pointer</div>
      <div class="pointer-domain"><span aria-hidden="true">○</span>none recorded</div>
    </div>`;
  }
  const dom = domainOf(row.pointer);
  const path = pathOf(row.pointer);
  return `<div class="pointer${dead ? ' pointer-dead' : ''}">
    <div class="pointer-label">${dead ? 'Pointer — the link checker could not reach it' : 'Where the work lives'}</div>
    <div class="pointer-domain"><span class="lock" aria-hidden="true">${dead ? '○' : '▣'}</span>${esc(dom)}</div>
    <a class="pointer-link" href="${href}" target="_blank" rel="noopener noreferrer nofollow ugc"
       aria-label="Open ${attr(dom)}${attr(path)} in a new tab"><span aria-hidden="true">${esc(trimPath(path))} ↗</span></a>
    ${dead ? `<div class="pointer-warn"><span aria-hidden="true">!</span><span>The link checker could not reach this. The claim is kept — verify before relying on it.</span></div>` : ''}
  </div>`;
}

/** Long paths get a middle ellipsis so the row stays one line tall. */
function trimPath(p) {
  if (p.length <= 78) return p;
  const head = p.slice(0, 36);
  const tail = p.slice(-34);
  return `${head}…${tail}`;
}

/* ---------------------------------------------------------------- evidence */

function evidenceBlock(row) {
  const ev = Array.isArray(row.evidence) ? row.evidence : [];
  if (!ev.length) return '';
  const items = ev
    .slice(0, 8)
    .map((e) => {
      const href = safeHref(e.url);
      const dom = esc(domainOf(e.url));
      return `<div class="evidence-item">
        <blockquote>&ldquo;${esc(e.quote || '')}&rdquo;</blockquote>
        <div class="ev-meta">
          <span class="ev-kind">${esc(e.kind || 'source')}</span>
          <span class="dom">${dom}</span>
          ${href ? `<a href="${href}" target="_blank" rel="noopener noreferrer nofollow ugc">source ↗</a>` : ''}
        </div>
      </div>`;
    })
    .join('');
  return `<details class="evidence">
    <summary>Evidence — ${ev.length} quoted ${plural(ev.length, 'source')}</summary>
    <div class="evidence-list">${items}</div>
  </details>`;
}

/* ------------------------------------------------------------------- cards */

function factsBlock(row, { emphasis = 'as_of' } = {}) {
  const asOf = row.as_of
    ? `<div class="kv kv-emphasis"><dt>Checked as of</dt><dd><time datetime="${attr(row.as_of)}">${esc(formatDate(row.as_of))}</time></dd></div>`
    : `<div class="kv kv-missing"><dt>As of</dt><dd>no date — treat with suspicion</dd></div>`;
  const parts = [asOf];
  if (emphasis !== 'as_of') parts.unshift(parts.pop()); // keep dominant field first
  parts.push(revFact(row), quantFact(row), modelRevFact(row), measurementFact(row), missingFact(row));
  return `<dl class="claim-facts">${parts.join('')}</dl>`;
}

function issueUrlFor(row) {
  const state = row.model_family === '*' ? 'context' : (row.status || 'unknown');
  const hw = row.hw_name ? `${row.hw_arch || ''} (${row.hw_name})` : (row.hw_arch || '');
  const title = `Evidence / issue: ${row.id || `${row.hw_arch || ''}/${row.model_family || ''}/${row.runtime || ''}`}`;
  const body = [
    `- **combo_id:** ${row.id || ''}`,
    `- **hardware:** ${hw}`,
    `- **model:** ${row.model_family || ''}`,
    `- **runtime:** ${row.runtime || ''}`,
    `- **state:** ${state}`,
    '',
    '### Evidence or issue details',
    ''
  ].join('\n');
  const params = new URLSearchParams({ title, body });
  return `https://github.com/BuildTreeFruits/solve-run/issues/new?${params.toString()}`;
}

function footBlock(row, { showId = true } = {}) {
  const bits = [];
  if (row.reported_by) bits.push(`reported by <span>${esc(row.reported_by)}</span>`);
  if (row.first_seen) bits.push(`first seen <time datetime="${attr(row.first_seen)}">${esc(formatDate(row.first_seen))}</time>`);
  if (showId && row.id) bits.push(`<span class="id">${esc(row.id)}</span>`);
  const actions = [];
  if (row.id) {
    actions.push(
      `<button type="button" class="btn btn-ghost btn-sm" data-copy-id="${attr(row.id)}">Copy id</button>`
    );
    actions.push(
      `<button type="button" class="btn btn-ghost btn-sm" data-link-row="${attr(row.id)}">Link to this</button>`
    );
  }
  actions.push(
    `<a class="btn btn-ghost btn-sm" href="${attr(issueUrlFor(row))}" target="_blank" rel="noopener noreferrer">Submit evidence / report issue</a>`
  );
  if (!actions.length && !bits.length) return '';
  return `<div class="card-foot">
    <span>${bits.join(' <span aria-hidden="true">·</span> ')}</span>
    <span class="spacer"></span>
    <div class="card-actions">${actions.join('')}</div>
  </div>`;
}

/** solved / rejected card: the claim, its date, where it lives, the evidence. */
function claimCard(row, { state }) {
  const rejected = state === 'rejected';
  const notes = row.notes
    ? rejected
      ? `<div class="notes-rejected"><div class="notes-eyebrow">Why it does not work here</div>${esc(row.notes)}</div>`
      : `<p class="notes">${esc(row.notes)}</p>`
    : '';
  const pointer = pointerBlock(row);
  return `<article class="card" data-state="${attr(state)}" data-row-id="${attr(row.id)}" tabindex="-1"
      aria-labelledby="t-${attr(cssId(row.id))}">
    <div class="card-head">
      ${stateChip(state)}
      <div class="chips">
        ${kindBadge(row.source_kind)}${derivedNote(row.source_kind)}${provenanceBadges(row)}
      </div>
    </div>
    <h3 class="card-title" id="t-${attr(cssId(row.id))}">${comboTitle(row)}</h3>
    <div class="card-sub">${hwLine(row)}<span class="dot" aria-hidden="true">·</span>${esc(row.runtime)}${row.runtime_rev ? ` pinned <code>${esc(row.runtime_rev)}</code>` : ''}</div>
    <div class="card-body">
      ${rejected ? notes : ''}
      <div class="card-cols">
        <div>${rejected ? '' : notes}${pointer}</div>
        <div>${factsBlock(row)}</div>
      </div>
      ${evidenceBlock(row)}
      ${rejected && row.pointer ? `<details class="details-row"><summary>Pointer that was tried</summary><div class="details-body">${pointer}</div></details>` : ''}
    </div>
    ${footBlock(row)}
  </article>`;
}

function solvedCard(row) {
  return claimCard(row, { state: 'solved' });
}

function rejectedCard(row) {
  // Equal prominence to solved: same card, same structure. "Do not hide it."
  return claimCard(row, { state: 'rejected' });
}

/** wanted card: the vote count is the loudest element; the age is visible. */
function wantedCard(row, { now = new Date(), voted = false } = {}) {
  const age = ageOf(row.want_first, now);
  const votes = row.want_votes || 0;
  const requesters = (row.want_requesters || []).slice(0, 8);
  const hidden = Math.max(0, (row.want_votes || 0) - requesters.length);
  const meter = ageMeter(age.days);
  const notes = row.notes ? `<p class="notes">${esc(row.notes)}</p>` : '';
  return `<article class="card" data-state="wanted" data-row-id="${attr(row.id)}" tabindex="-1"
      aria-labelledby="t-${attr(cssId(row.id))}">
    <div class="card-head">
      ${stateChip('wanted')}
      <div class="chips">${kindBadge(row.source_kind)}${derivedNote(row.source_kind)}${provenanceBadges(row)}</div>
    </div>
    <h3 class="card-title" id="t-${attr(cssId(row.id))}">${comboTitle(row)}</h3>
    <div class="card-sub">${hwLine(row)}<span class="dot" aria-hidden="true">·</span>${esc(row.runtime)}</div>
    <div class="card-body">
      <div class="wanted-block">
        <div class="vote-count" aria-label="${votes} ${plural(votes, 'person wants')} this">
          <span class="n">${esc(votes)}</span>
          <span class="l">${plural(votes, 'vote')}</span>
        </div>
        <div class="wanted-meta">
          <div class="row"><span class="k">First wanted</span>
            <time datetime="${attr(row.want_first || '')}">${esc(row.want_first ? formatDate(row.want_first) : 'unknown date')}</time>
            <span class="age" data-age="${attr(age.bucket)}">
              <span aria-hidden="true">${age.bucket === 'stale' ? '⚠' : age.bucket === 'aging' ? '·' : '○'}</span>
              wanted ${esc(age.text)}
              ${meter}
            </span>
          </div>
          <div class="row"><span class="k">Wanted by</span>
            <span class="requesters">${
              requesters.length
                ? requesters.map((r) => `<span class="requester">${esc(r)}</span>`).join('') +
                  (hidden > 0 ? `<span class="requester more">+${esc(hidden)} more</span>` : '')
                : `<span style="color:var(--ink-3)">vote list not shown (per-voter keys kept private)</span>`
            }</span>
          </div>
          <div class="row"><span class="k">Last activity</span><span>${esc(row.updated ? formatDate(row.updated) : formatDate(row.as_of))}</span></div>
        </div>
        <div class="wanted-actions">
          <button type="button" class="btn btn-want" data-vote="${attr(row.id)}"
            data-voted="${voted ? 'true' : 'false'}" aria-pressed="${voted ? 'true' : 'false'}"
            aria-label="${voted ? 'You want this' : 'Vote that you want'} this combination, ${votes} so far">
            <span aria-hidden="true">${voted ? '✓' : '↑'}</span><span class="vote-label">${voted ? 'Wanted' : 'I want this'}</span>
          </button>
        </div>
      </div>
      ${notes}
      ${evidenceBlock(row)}
    </div>
    ${footBlock(row)}
  </article>`;
}

function ageMeter(days) {
  const lvl = ageLevel(days);
  const bars = [0, 1, 2]
    .map((i) => `<i class="${i < lvl ? 'on' : ''}"></i>`)
    .join('');
  return `<span class="age-meter" aria-hidden="true">${bars}</span>`;
}

/** `*` row: hardware-level claim. Never rendered as a model answer. */
function contextCard(row) {
  const notes = row.notes ? `<p class="notes">${esc(row.notes)}</p>` : '';
  return `<article class="card" data-state="context" data-row-id="${attr(row.id)}" tabindex="-1"
      aria-labelledby="t-${attr(cssId(row.id))}">
    <div class="card-head">
      ${stateChip('context')}
      <div class="chips">${kindBadge(row.source_kind)}${derivedNote(row.source_kind)}${provenanceBadges(row)}</div>
    </div>
    <h3 class="card-title" id="t-${attr(cssId(row.id))}">
      ${esc(row.hw_arch)}<span class="sep" aria-hidden="true"> × </span><span class="part">all models</span><span class="sep" aria-hidden="true"> × </span><span class="part">${esc(row.runtime)}</span>
    </h3>
    <div class="card-sub">${hwLine(row)}<span class="dot" aria-hidden="true">·</span>applies to every model on this card</div>
    <div class="card-body">
      ${notes}
      <div class="card-cols">
        <div>${pointerBlock(row)}</div>
        <div>${factsBlock(row)}</div>
      </div>
      ${evidenceBlock(row)}
    </div>
    ${footBlock(row)}
  </article>`;
}

function cardFor(row, opts = {}) {
  if (row.model_family === '*') return contextCard(row, opts);
  if (row.status === 'wanted') return wantedCard(row, opts);
  if (row.status === 'rejected') return rejectedCard(row, opts);
  return solvedCard(row, opts);
}

/* ================================================================ MISS PANEL
   The deciding test from the blueprint: "open the site, search for a
   combination that does not exist, and see it say so plainly with a date."
   So: big plain sentence, the dataset date, the counts, one honest paragraph
   about what this means, a want button, and the exact JSON payload.
   ======================================================================== */

function missPanel(response, { now = new Date(), payload }) {
  const miss = response.miss || {};
  const q = response.query || {};
  const ds = response.dataset || {};
  const reason = REASON_META[miss.reason] ? miss.reason : 'no-claim';
  const meta = REASON_META[reason];
  const sentence = missSentence(q);

  // Render the sentence with the typed parts highlighted (still one text string
  // in the accessible name, via aria-label on the heading).
  const parts = [q.hw, q.model, q.runtime].filter((v) => v !== null && v !== undefined && v !== '');
  const sentenceHtml =
    parts.length
      ? `No claim on record for ${parts.map((p) => `<span class="part">${esc(p)}</span>`).join('<span class="sep" aria-hidden="true"> × </span>')}`
      : 'No claim on record for any combination';

  // Counts are taken from the payload, but cross-checked against what is
  // actually rendered: if the API says 0 context rows while context rows are
  // attached, trust the rows. A counter that contradicts the sentence is worse
  // than no counter at all — this product's whole claim is that it doesn't lie.
  const attached = Array.isArray(response.context) ? response.context.length
    : Array.isArray(response.hardware_level) ? response.hardware_level : 0;
  const counts = {
    exact: Math.max(0, (miss.counts && miss.counts.exact) || 0),
    context: Math.max((miss.counts && miss.counts.context) || 0, attached)
  };
  const asOf = ds.as_of;
  const facts = [
    asOf
      ? `<div class="fact fact-asof"><dt>Dataset as of</dt><dd><time datetime="${attr(asOf)}">${esc(formatDate(asOf))}</time></dd></div>`
      : `<div class="fact fact-asof"><dt>Dataset as of</dt><dd>no date <small>— treat with suspicion</small></dd></div>`,
    `<div class="fact"><dt>Model-specific claims</dt><dd>${esc(counts.exact || 0)}</dd></div>`,
    `<div class="fact"><dt>Hardware-level claims</dt><dd>${esc(counts.context || 0)}</dd></div>`,
    `<div class="fact"><dt>Rows in dataset</dt><dd>${esc(ds.rows ?? '—')}</dd></div>`,
    miss.wanted_votes
      ? `<div class="fact"><dt>Votes on this</dt><dd>${esc(miss.wanted_votes)}</dd></div>`
      : '',
    miss.known_wanted
      ? `<div class="fact"><dt>Wanted</dt><dd>yes <small>on record</small></dd></div>`
      : `<div class="fact"><dt>Wanted</dt><dd>not yet <small>0 votes</small></dd></div>`,
    miss.last_checked
      ? `<div class="fact"><dt>Last check</dt><dd>${esc(formatDate(miss.last_checked))}</dd></div>`
      : `<div class="fact"><dt>Last check</dt><dd>never <small>no record</small></dd></div>`
  ]
    .filter(Boolean)
    .join('');

  return `<section class="miss" data-reason="${attr(reason)}" tabindex="-1" aria-labelledby="miss-title"
     aria-describedby="miss-hint">
    <div class="miss-main">
      <div class="miss-eyebrow">
        <span aria-hidden="true">∅</span> Not searched — recorded gap
        <span class="reason">${esc(meta.label)}</span>
      </div>
      <h2 class="miss-sentence" id="miss-title" aria-label="${attr(sentence)}">${sentenceHtml}</h2>
      <p class="miss-hint" id="miss-hint">${esc(miss.hint || meta.lead)}</p>
      <div class="miss-means">
        <span class="glyph" aria-hidden="true">ⓘ</span>
        <span>This is a <b>recorded gap, not a broken page</b>. The index has been searched and has no claim for
        this combination${asOf ? `, as of <time datetime="${attr(asOf)}">${esc(formatDate(asOf))}</time>` : ''}.
        That is information: nothing is known to work here, and nothing is known to fail.</span>
      </div>
      <dl class="miss-facts">${facts}</dl>
      <div class="miss-actions">
        <button type="button" class="btn btn-want" data-want-miss
          data-id="${attr(payload.id)}" aria-pressed="false">
          <span aria-hidden="true">↑</span><span class="vote-label">Want this</span>
        </button>
        <button type="button" class="btn btn-ghost" data-copy-payload>Copy miss report</button>
        <button type="button" class="btn btn-ghost" data-copy-link>Copy link to this lookup</button>
        <span class="feedback" data-miss-feedback role="status" aria-live="polite"></span>
      </div>
    </div>
    <div class="miss-side">
      <div>
        <div class="side-title">The machine-readable answer</div>
        <p class="side-note">Paste this into an agent, an issue, or a message. A miss is a contribution: it
        is how the wanted list fills itself.</p>
      </div>
      <details class="payload">
        <summary>miss payload (JSON)</summary>
        <pre tabindex="0" data-json="${attr(JSON.stringify(payload))}">${esc(prettyJson(payload))}</pre>
        <div class="payload-actions">
          <button type="button" class="btn btn-ghost btn-sm" data-copy-payload>Copy</button>
          <button type="button" class="btn btn-ghost btn-sm" data-download-payload>Download .json</button>
        </div>
      </details>
      <div class="side-note">The same answer is at <span class="mono">GET /api/lookup?hw=…&amp;model=…&amp;runtime=…</span></div>
    </div>
  </section>`;
}

/* ------------------------------------------------------- empty / error */

function emptyDataset({ error, source, dataset, onRetryId = 'retry' } = {}) {
  return `<section class="empty-state" role="status">
    <h2>No data yet</h2>
    <p>The index is deployed but has no rows loaded. This is not a miss — a miss means the index was
    searched and found nothing. Here, the index has nothing to search.</p>
    ${error ? `<p><code>${esc(error)}</code></p>` : ''}
    <p>Build the export with <code>python3 pipeline/build.py</code> (or start the bundled server with
    <code>python3 scripts/serve.py</code>), then reload.</p>
    <button type="button" class="btn btn-primary" id="${attr(onRetryId)}">Reload</button>
  </section>`;
}

function loadError({ message, tried = [] } = {}) {
  return `<section class="empty-state" role="alert">
    <h2>Couldn’t load the index</h2>
    <p>${esc(message || 'The dataset could not be loaded.')}</p>
    ${tried.length ? `<p style="font-size:var(--step--1)">Tried: <code>${tried.map(esc).join('</code>, <code>')}</code></p>` : ''}
    <button type="button" class="btn btn-primary" id="retry">Try again</button>
  </section>`;
}

function loading(label = 'Loading the index…') {
  return `<div class="loading" role="status"><span class="spinner" aria-hidden="true"></span>${esc(label)}</div>`;
}

/* ------------------------------------------------------------- sections */

function contextSection(rows, { now, voted = new Set(), heading = 'Hardware-level support for this card' } = {}) {
  if (!rows || !rows.length) return '';
  const cards = rows.map((r) => contextCard(r, { now, voted })).join('');
  return `<section class="context-section" aria-labelledby="ctx-heading">
    <div class="context-head">
      <h3 id="ctx-heading">${esc(heading)} <span style="font-weight:500;color:var(--ink-3)">(applies to all models)</span></h3>
      <p class="why">These rows are claims about the <em>card and runtime</em>, not about any model. They say the
      backend builds on this hardware. They do not say a specific model runs here — so they are not counted as an
      answer above.</p>
    </div>
    <div class="cards-context">${cards}</div>
  </section>`;
}

/** The "here is what does exist for this card" hint under a miss — stays secondary. */
function neighbouringNote(rows, q) {
  if (!rows || !rows.length) return '';
  const list = rows
    .slice(0, 6)
    .map((r) => `<button type="button" class="chip" data-try-hw="${attr(r.hw_arch)}" data-try-runtime="${attr(r.runtime)}" data-try-vendor="${attr(r.hw_vendor)}">
      ${esc(r.hw_arch)} · ${esc(r.model_family === '*' ? 'all models' : r.model_family)} · ${esc(r.runtime)}
      <span class="n">${esc(STATE_META[r.status]?.label || r.status)}</span></button>`)
    .join('');
  return `<section class="results-head" style="border:0;padding:0;margin-top:20px;display:block">
    <div style="font-size:var(--step--1);color:var(--ink-3);margin-bottom:8px">
      Related rows${q && q.hw ? ` for ${esc(q.hw)}` : ''} — each opens as its own lookup:
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">${list}</div>
  </section>`;
}

/* ---------------------------------------------------------------- browse */

const BROWSE_COLUMNS = [
  { key: 'status', label: 'State' },
  { key: 'hw_vendor', label: 'Vendor' },
  { key: 'hw_arch', label: 'Hardware' },
  { key: 'model_family', label: 'Model' },
  { key: 'runtime', label: 'Runtime' },
  { key: 'as_of', label: 'As of' },
  { key: 'want_votes', label: 'Votes', numeric: true },
  { key: 'source_kind', label: 'Source' },
  { key: '', label: '' }
];

function browseTable(rows, { sort, dir, now, voted = new Set(), total = rows.length } = {}) {
  const head = BROWSE_COLUMNS.map((c) => {
    if (!c.key) return `<th scope="col"><span class="visually-hidden">Actions</span></th>`;
    const isSorted = sort === c.key;
    const ariaSort = isSorted ? (dir === 'asc' ? 'ascending' : 'descending') : 'none';
    const next = isSorted && dir === 'asc' ? 'desc' : 'asc';
    return `<th scope="col" aria-sort="${ariaSort}"${c.numeric ? ' style="text-align:right"' : ''}>
      <button type="button" data-sort="${attr(c.key)}" data-dir="${attr(next)}">${esc(c.label)}</button></th>`;
  }).join('');

  const body = rows
    .map((r) => {
      const state = r.model_family === '*' ? 'context' : r.status;
      const isWanted = state === 'wanted';
      const age = isWanted ? ageOf(r.want_first, now) : null;
      return `<tr data-status="${attr(r.status || '')}" class="${r.model_family === '*' ? 'is-context' : ''}">
        <td class="c-status">${stateChip(state)}</td>
        <td class="c-vendor">${esc(r.hw_vendor || '—')}</td>
        <td class="c-hw"><span class="arch">${esc(r.hw_arch || '—')}</span>${r.hw_name ? `<span class="nm">${esc(r.hw_name)}</span>` : ''}</td>
        <td class="c-model">${r.model_family === '*' ? '<span class="star" title="Hardware-level claim, applies to all models">＊</span> <span style="color:var(--ink-3)">all</span>' : `<code>${esc(r.model_family)}</code>`}</td>
        <td class="c-runtime">${esc(r.runtime)}</td>
        <td class="c-asof"><time datetime="${attr(r.as_of || '')}">${esc(formatDateShort(r.as_of))}</time>${isWanted && age ? `<div class="age" data-age="${attr(age.bucket)}">${esc(age.text)}</div>` : ''}</td>
        <td class="c-votes">${isWanted ? esc(r.want_votes || 0) : '<span style="color:var(--ink-3)">—</span>'}</td>
        <td class="c-kind">${kindBadge(r.source_kind)}${r.pointer_alive === false ? ' <span class="badge badge-dead" title="Pointer may be dead">● dead?</span>' : ''}${r.provisional ? ' <span class="badge badge-provisional">Provisional</span>' : ''}</td>
        <td><button type="button" class="row-open" data-open-row="${attr(r.id)}" aria-label="Open lookup for ${attr(r.hw_arch)} × ${attr(r.model_family === '*' ? 'all models' : r.model_family)} × ${attr(r.runtime)}">Open</button></td>
      </tr>`;
    })
    .join('');

  if (!rows.length) {
    return `<div class="empty-state" style="margin-top:14px"><p>No rows match these filters.</p></div>`;
  }
  return `<div class="table-wrap">
    <table class="rows">
      <caption class="visually-hidden">All ${total} rows in the dataset, ${rows.length} shown</caption>
      <thead><tr>${head}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  </div>`;
}

  Object.assign(SR, { esc, cssId, STATE_META, KIND_META, stateChip, kindBadge, comboTitle, pointerBlock, evidenceBlock, solvedCard, rejectedCard, wantedCard, contextCard, cardFor, missPanel, emptyDataset, loadError, loading, contextSection, neighbouringNote, browseTable });
})(window.__SR = window.__SR || {});
