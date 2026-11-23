/* app.js — classic script build (see web/tools/to-classic.mjs).
   Loaded in order from index.html so the site also works from file://,
   where browsers block ES modules and fetch(). Source of truth is this file. */
(function (SR) {
'use strict';
  // dependencies pulled from the shared namespace
  const { lookup, buildQuery, facets, sortRows, sortWanted, normalizeRow, getAllRows, getLookup, reportMiss, voteFor, clearStaticCache, loadTaxonomy, ageOf } = SR;

/**
 * app.js — wiring only. All rendering lives in render.js, all matching in
 * lookup.js, all data access in api.js. This file owns DOM state, routing,
 * keyboard and events.
 *
 * URL is the source of truth for a lookup:
 *   #lookup?hw=sm_86&model=qwen3&runtime=llama.cpp
 *   #browse?status=wanted&sort=want_votes
 * so any answer can be linked, pasted into an issue, or handed to an agent.
 */

  // Bind the render namespace used throughout this file.
  const R = SR;

/* ------------------------------------------------------------------ state */

const state = {
  rows: [],
  dataset: null,
  source: null, // 'api' | 'static' | 'snapshot'
  facets: null,
  votes: loadVoted(), // Set of row ids voted for in this browser
  lastResponse: null,
  taxonomy: null,
  view: 'lookup',
  browse: { status: '', vendor: '', q: '', sort: 'status', dir: 'desc' }
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const el = {
  results: $('#results'),
  form: $('#search-form'),
  hw: $('#hw-input'),
  model: $('#model-input'),
  runtime: $('#runtime-select'),
  hwList: $('#hw-list'),
  modelList: $('#model-list'),
  banner: $('#data-banner'),
  bannerText: $('#data-banner-text'),
  status: $('#search-status'),
  starters: $('#starters'),
  startersList: $('#starters-list'),
  hwJump: $('#hw-jump'),
  hwJumpList: $('#hw-jump-list'),
  datasetLine: $('#dataset-line'),
  footerVersion: $('#footer-version'),
  browseCoverage: $('#browse-coverage'),
  browseResults: $('#browse-results'),
  browseMeta: $('#browse-meta'),
  browseQ: $('#browse-q'),
  toast: $('#toast')
};

/* ---------------------------------------------------------------- helpers */

function toast(msg) {
  el.toast.textContent = msg;
  el.toast.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.toast.classList.remove('show'), 2400);
}

async function copyText(text, okMsg) {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMsg || 'Copied');
    return true;
  } catch {
    // file:// and some browsers deny the async clipboard API — fall back.
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:-9999px;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    document.body.removeChild(ta);
    toast(ok ? okMsg || 'Copied' : 'Copy failed — select the text manually');
    return ok;
  }
}

function loadVoted() {
  try {
    return new Set(JSON.parse(localStorage.getItem('solve.run.voted') || '[]'));
  } catch {
    return new Set();
  }
}
function saveVoted() {
  try {
    localStorage.setItem('solve.run.voted', JSON.stringify([...state.votes]));
  } catch {
    /* private mode: votes still submit, just not remembered locally */
  }
}

function voterKey() {
  let k = null;
  try {
    k = localStorage.getItem('solve.run.voter');
  } catch {
    /* ignore */
  }
  if (!k) {
    const rand = Math.random().toString(36).slice(2, 10);
    k = `web-${rand}`;
    try {
      localStorage.setItem('solve.run.voter', k);
    } catch {
      /* ignore */
    }
  }
  return k;
}

/** Row id for a lookup the index has never stored (the miss / want path). */
/**
 * The id a not-yet-stored combination would have (CONTRACT §2), used as the key
 * for a want-vote from the miss panel. A missing runtime maps to the taxonomy's
 * `unknown` slug rather than an invented one, so the id stays the shape the
 * pipeline would create once the miss log promotes it to a row.
 */
function normIdToken(s) {
  return String(s || '')
    .trim()
    .toLowerCase()
    .replace(/[._\s/]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function compactIdToken(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function slugSegment(v, fallback) {
  const s = String(v || '')
    .trim()
    .toLowerCase()
    .replace(/\./g, '_')
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s || fallback;
}

function resolveVendorForArch(arch) {
  const tax = state.taxonomy;
  const normArch = normIdToken(arch);
  if (tax && tax.hw_archs) {
    for (const [vendor, arches] of Object.entries(tax.hw_archs)) {
      if (Array.isArray(arches) && arches.some((a) => a === arch || normIdToken(a) === normArch)) {
        return vendor;
      }
    }
  }
  const rowMatch = state.rows.find((r) => r.hw_arch === arch || normIdToken(r.hw_arch) === normArch);
  if (rowMatch && rowMatch.hw_vendor) return rowMatch.hw_vendor;

  const a = String(arch || '').toLowerCase();
  if (/^(sm_|rtx|gtx|tesla|quadro|jetson|dgx|gb[12]0|h[12]00|a[1346]0|b[123]00|l40|t4|v100|p100|p40|m40)/.test(a)) return 'nvidia';
  if (/^(gfx|rx-?[0-9]|radeon|instinct|mi[0-9]|strix|ryzen-ai|w[67][0-9]{3}|r9700)/.test(a)) return 'amd';
  if (/^(arc-|data-center-max|flex-|intel-|gaudi|xeon|core-ultra|lunar-lake|meteor-lake|arrow-lake|panther-lake)/.test(a)) return 'intel';
  if (/^(m[1-9]($|[-_])|a1[5-9]($|[-_])|apple|mac-|macbook)/.test(a)) return 'apple';
  if (/^(snapdragon|hexagon|adreno)/.test(a)) return 'qualcomm';
  if (/^(aarch64|arm64|armv[89]|graviton|ampereone|grace-cpu|cortex)/.test(a)) return 'arm-cpu';
  if (/^(x86|avx|sse|amx|zen[2-6]|epyc)/.test(a)) return 'x86-cpu';
  return 'other';
}

function idFor(q) {
  const tax = state.taxonomy;
  let arch = '';
  if (q && q.hw) {
    if (SR.resolveHwAlias) {
      arch = SR.resolveHwAlias(q.hw, tax) || q.hw;
    } else if (tax && tax.hw_aliases) {
      const n = normIdToken(q.hw);
      const c = compactIdToken(q.hw);
      for (const [alias, target] of Object.entries(tax.hw_aliases)) {
        if (normIdToken(alias) === n || compactIdToken(alias) === c) {
          arch = target;
          break;
        }
      }
      if (!arch) arch = q.hw;
    } else {
      arch = q.hw;
    }
  }
  const archSlug = slugSegment(arch, 'unknown');
  const vendorSlug = q && q.hw ? slugSegment(resolveVendorForArch(archSlug), 'other') : 'other';

  let model = q && q.model ? q.model : '';
  if (model) {
    if (SR.resolveModelAlias) {
      model = SR.resolveModelAlias(model, tax) || model;
    } else if (tax && Array.isArray(tax.models)) {
      const n = normIdToken(model);
      const c = compactIdToken(model);
      for (const m of tax.models) {
        const aliases = Array.isArray(m.aliases) ? m.aliases : [];
        if (aliases.some((al) => normIdToken(al) === n || compactIdToken(al) === c)) {
          model = m.family;
          break;
        }
      }
    }
  }
  const modelSlug = slugSegment(model, 'unknown');
  const runtimeSlug = slugSegment(q && q.runtime, 'unknown');
  return `${vendorSlug}/${archSlug}/${modelSlug}/${runtimeSlug}`;
}

/* ------------------------------------------------------------------- data */

async function boot() {
  setView(routeView(), { silent: true });
  bindEvents();
  await loadData();
  await route();
}

async function loadData() {
  el.results.innerHTML = R.loading();
  try {
    const data = await getAllRows();
    state.rows = data.rows;
    state.dataset = data.dataset;
    state.source = data.source;
    state.facets = facets(data.rows);
    if (state.source === 'snapshot' && window.SOLVE_RUN_SNAPSHOT && window.SOLVE_RUN_SNAPSHOT.taxonomy) {
      state.taxonomy = window.SOLVE_RUN_SNAPSHOT.taxonomy;
    } else if (!state.taxonomy) {
      state.taxonomy = await loadTaxonomy().catch(() => null);
    }
    renderChrome();
    return true;
  } catch (err) {
    state.rows = [];
    state.dataset = null;
    el.results.innerHTML = R.loadError({ message: err.message, tried: ['/api/lookup', '../data/combos.json', 'snapshot.js'] });
    const retry = $('#retry');
    if (retry) retry.addEventListener('click', () => loadData().then(() => route()));
    renderChrome();
    return false;
  }
}

/** header, banner, runtime select, footer — everything outside the results. */
function renderChrome() {
  const ds = state.dataset || {};
  const isSnapshot = state.source === 'snapshot';
  const empty = state.rows.length === 0;

  // Runtime select from taxonomy runtimes ∪ runtimes present in data.
  const runtimes = state.facets ? state.facets.runtimes.map((r) => r.value) : [];
  const current = el.runtime.value;
  el.runtime.innerHTML =
    `<option value="">Any runtime</option>` +
    runtimes.map((r) => `<option value="${R.esc(r)}">${R.esc(r)}</option>`).join('');
  if (runtimes.includes(current)) el.runtime.value = current;

  // Banner: offline snapshot / no data. Honesty is non-negotiable.
  el.banner.hidden = !(isSnapshot || empty);
  if (isSnapshot) {
    el.bannerText.innerHTML =
      `<strong>Offline snapshot.</strong> Opened from a local file, so the page is showing a saved copy of the dataset` +
      `${ds.as_of ? ` as of <strong>${R.esc(ds.as_of)}</strong>` : ''} (${R.esc(ds.rows)} rows) instead of the live index. ` +
      `Run <code>python3 scripts/serve.py</code> and open http://127.0.0.1:8787/ for live data and working votes.`;
  } else if (empty) {
    el.bannerText.innerHTML = `<strong>No rows loaded.</strong> The index is up but the dataset is empty — that is different from a miss.`;
  }

  el.datasetLine.dataset.source = state.source || 'unknown';
  const srcLabel =
    state.source === 'api'
      ? 'Live API'
      : state.source === 'static'
        ? 'Static export'
        : state.source === 'snapshot'
          ? 'Offline snapshot'
          : 'Unavailable';
  el.datasetLine.innerHTML = `<span class="src">${R.esc(srcLabel)}</span>` +
    (ds.version ? ` <span>· version <code>${R.esc(ds.version)}</code></span>` : '') +
    (ds.as_of ? ` <span>· as of <strong>${R.esc(ds.as_of)}</strong></span>` : '') +
    ` <span>· ${R.esc(ds.rows ?? 0)} rows</span>`;
  el.footerVersion.textContent = `${ds.version ? `dataset ${ds.version} · ` : ''}${ds.as_of ? `as of ${ds.as_of} · ` : ''}${ds.rows ?? 0} rows`;

  // Footer API links and voting UI only make sense when the API exists.
  const apiOk = state.source === 'api';
  $$('[data-api-only]').forEach((node) => {
    node.hidden = !apiOk;
  });
  if (!apiOk && state.browse.sort === 'want_votes') {
    state.browse.sort = 'status';
    if (el.browseSort) el.browseSort.value = 'status';
  }
  $$('[data-href-api]').forEach((a) => {
    if (!apiOk) {
      const key = a.dataset.hrefApi;
      a.setAttribute('aria-disabled', 'true');
      a.title = 'The API is not available in this hosting mode (static export).';
      if (key === 'lookup' || key === 'docs') a.href = '#';
    }
  });

  // Browse counts
  const counts = { all: state.rows.filter((r) => r.model_family !== '*').length, solved: 0, untested: 0, rejected: 0, context: 0 };
  for (const r of state.rows) {
    if (r.model_family === '*') counts.context++;
    else if (r.status === 'wanted' || r.status === 'untested') counts.untested++;
    else if (counts[r.status] !== undefined) counts[r.status]++;
  }
  $$('[data-count]').forEach((n) => {
    n.textContent = counts[n.dataset.count] ?? 0;
  });
  const navCount = $('[data-nav-count]');
  if (navCount) {
    navCount.textContent = String(ds.rows ?? state.rows.length);
    navCount.hidden = false;
  }

  renderHwJump();
  renderStarters();
}

/**
 * Starters are built by *querying the loaded dataset*, not by trusting it to
 * contain a particular state. Each one is verified to produce the state it
 * advertises, so a starter can never land on a surprise page.
 *
 * Every starter is checked with the same `lookup()` the page uses, which is why
 * this runs after data load and never hits the network.
 */
function renderHwJump() {
  if (!el.hwJump || !el.hwJumpList) return;
  const counts = new Map();
  for (const r of state.rows) {
    if (!r.hw_arch) continue;
    counts.set(r.hw_arch, (counts.get(r.hw_arch) || 0) + 1);
  }
  const top = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 10);
  if (!top.length) {
    el.hwJump.hidden = true;
    return;
  }
  el.hwJump.hidden = false;
  el.hwJumpList.innerHTML = top
    .map(([arch, count]) =>
      `<button type="button" class="chip" data-jump-hw="${R.esc(arch)}">${R.esc(arch)} <span class="n">${R.esc(count)}</span></button>`
    )
    .join('');
  el.hwJumpList.querySelectorAll('[data-jump-hw]').forEach((btn) => {
    btn.addEventListener('click', () => {
      performLookup({ hw: btn.dataset.jumpHw, model: null, runtime: null }, { push: true });
    });
  });
}

function renderStarters() {
  const starters = [];
  const rows = state.rows;
  const ds = state.dataset || {};
  const faceted = facets(rows);

  const asQuery = (r, withModel = true) => ({
    hw: r.hw_arch,
    model: withModel && r.model_family !== '*' ? r.model_family : null,
    runtime: r.runtime || null
  });
  const shows = (q, pred) => {
    const res = lookup(rows, q, ds, state.taxonomy);
    return pred(res);
  };

  // 1. solved — a real pointer with a date. Prefer a recognisable card over a
  //    generic placeholder arch when the dataset happens to have both.
  const GENERIC_ARCH = /(^generic$|^unknown$|^other$)/;
  const solvedCandidates = sortRows(
    rows.filter((r) => r.status === 'solved' && r.model_family !== '*' && r.pointer)
  ).sort((a, b) => Number(GENERIC_ARCH.test(a.hw_arch)) - Number(GENERIC_ARCH.test(b.hw_arch)));
  const solved = solvedCandidates.find((r) => shows(asQuery(r), (res) => res.rows.some((x) => x.id === r.id)));
  if (solved) {
    starters.push({
      tone: 'solved',
      label: 'A solved combination',
      q: asQuery(solved, true),
      d: `${solved.hw_arch} × ${solved.model_family} — a pointer, pinned and dated`,
      expect: 'solved'
    });
  }

  // 2. rejected — equal prominence to solved. Model-specific rows only: a `*`
  //    rejected row would read as "this card can't run anything", which is a
  //    different and stronger claim than "this model doesn't work here".
  const rejectedCandidates = rows.filter((r) => r.status === 'rejected' && r.model_family !== '*');
  const rejected = rejectedCandidates.find((r) => shows(asQuery(r), (res) => res.rows.some((x) => x.id === r.id)));
  if (rejected) {
    starters.push({
      tone: 'rejected',
      label: 'A rejected combination',
      q: asQuery(rejected, true),
      d: `${rejected.hw_arch} × ${rejected.model_family} — tried, does not work here`,
      expect: 'rejected'
    });
  }

  // 3. untested — most wanted first (CONTRACT: votes desc, then oldest)
  const wanted = sortWanted(rows.filter((r) => (r.status === 'untested' || r.status === 'wanted') && r.model_family !== '*')).find((r) =>
    shows(asQuery(r), (res) => res.rows.some((x) => x.id === r.id))
  );
  if (wanted) {
    starters.push({
      tone: 'untested',
      label: 'Something untested',
      q: asQuery(wanted, true),
      d: `${wanted.hw_arch} × ${wanted.model_family} — ${wanted.want_votes || 0} ${(wanted.want_votes || 0) === 1 ? 'vote' : 'votes'}, nobody has solved it`,
      expect: 'untested'
    });
  }

  // 4. a guaranteed miss. Prefer a real hardware-level `*` row so the miss
  //    demonstrates partial-context (the most instructive shape); otherwise use
  //    a card from the taxonomy that has no rows at all.
  const missQ = findGuaranteedMiss(rows, faceted, ds);
  if (missQ) {
    starters.push({
      tone: 'miss',
      label: 'A combination nobody recorded',
      q: missQ.q,
      d: `${missQ.q.hw} × ${missQ.q.model} — a recorded gap, with a date`,
      expect: 'miss'
    });
  }

  el.starters.hidden = starters.length === 0;
  el.startersList.innerHTML = starters
    .map(
      (s) => `<button type="button" class="starter" data-tone="${R.esc(s.tone)}" data-starter='${R.esc(JSON.stringify(s.q))}'>
        <span class="t">${R.esc(s.label)} <span aria-hidden="true">→</span></span>
        <span class="d">${R.esc(s.d)}</span>
      </button>`
    )
    .join('');
}

/** Plausible model names that no local-inference index is likely to have rows for. */
const MISS_MODEL_POOL = ['kimi', 'ernie', 'hunyuan', 'internlm', 'yi', 'olmo', 'granite', 'devstral', 'codestral', 'acestep'];

/**
 * Find a query that is certain to be a miss, verified by running lookup().
 * Order of preference:
 *   1. a hardware-level (`*`) card + a model with no rows anywhere -> partial-context
 *   2. a real card (from data or taxonomy) + a nonexistent model -> no-match / partial
 * Returns null only if every candidate accidentally matches, in which case the
 * starter is simply omitted rather than shown broken.
 */
function findGuaranteedMiss(rows, faceted, ds) {
  const familiesWithRows = new Set(rows.filter((r) => r.model_family !== '*').map((r) => r.model_family));
  const model = MISS_MODEL_POOL.find((m) => !familiesWithRows.has(m) && ![...familiesWithRows].some((f) => f.includes(m) || m.includes(f)));
  if (!model) return null;

  const isMiss = (q) => {
    const res = lookup(rows, q, ds, state.taxonomy);
    return res.miss && res.miss.is_miss && res.miss.reason !== 'no-match' ? true : res.miss && res.miss.is_miss ? true : false;
  };

  const starRows = rows.filter((r) => r.model_family === '*' && r.status === 'solved');
  for (const r of starRows) {
    const q = { hw: r.hw_arch, model, runtime: null };
    const res = lookup(rows, q, ds, state.taxonomy);
    if (res.miss && res.miss.is_miss) return { q, reason: res.miss.reason };
  }

  // any card already in the data
  for (const a of faceted.arches) {
    if (starRows.some((r) => r.hw_arch === a.value)) continue;
    const q = { hw: a.value, model, runtime: null };
    const res = lookup(rows, q, ds, state.taxonomy);
    if (res.miss && res.miss.is_miss) return { q, reason: res.miss.reason };
  }

  // a taxonomy arch with zero rows, so even an empty dataset can demo a miss
  const taxonomyArchs = (state.taxonomy && state.taxonomy.hw_archs) || {};
  for (const [vendor, archs] of Object.entries(taxonomyArchs)) {
    for (const arch of archs || []) {
      if (faceted.arches.some((a) => a.value === arch)) continue;
      const q = { hw: arch, model, runtime: null };
      if (isMiss(q)) return { q, reason: 'no-match' };
    }
  }
  return null;
}

/* ------------------------------------------------------------------ views */

function routeView() {
  const h = location.hash.replace(/^#/, '');
  if (h.startsWith('browse')) return 'browse';
  return 'lookup';
}

function setView(view, { silent = false } = {}) {
  state.view = view;
  $$('[data-view]').forEach((s) => s.classList.toggle('active', s.dataset.view === view));
  $$('[data-nav]').forEach((a) => {
    if (a.dataset.nav === view) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  if (!silent) document.title = view === 'browse' ? 'Browse all combinations — solve.run' : 'solve.run — does this combination exist?';
}

/**
 * The effective lookup params. Two accepted forms, because both get pasted:
 *
 *   #lookup?hw=sm_86&model=qwen3       (canonical; what Copy link produces)
 *   ?hw=sm_86&model=qwen3              (plain query string, agent-friendly)
 *
 * The hash wins when it carries params; otherwise the query string is used.
 * Match params are read from both, so a partial query string still works when a
 * hash is present for another reason (e.g. `#lookup`).
 */
function readLookupParams() {
  const hash = location.hash.replace(/^#/, '');
  const hashQs = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : '';
  const search = new URLSearchParams(location.search);
  const merged = new URLSearchParams();
  for (const [k, v] of search) if (!['hw', 'model', 'runtime', 'status', 'kind', 'q', 'limit'].includes(k)) continue; else merged.set(k, v);
  if (hashQs) for (const [k, v] of new URLSearchParams(hashQs)) merged.set(k, v);
  return merged;
}

/** Kept as an alias: some call sites read "the hash params". */
function readHashQuery() {
  return readLookupParams();
}

/* ------------------------------------------------------------------ lookup */

function currentQuery() {
  return {
    hw: el.hw.value.trim() || null,
    model: el.model.value.trim() || null,
    runtime: el.runtime.value || null,
    status: null,
    kind: null,
    q: null,
    limit: 50
  };
}

function isBlank(q) {
  return !q.hw && !q.model && !q.runtime;
}

async function performLookup(q, { push = true } = {}) {
  const clean = buildQuery(q);
  if (push) writeHash(clean, 'lookup');

  if (isBlank(clean)) {
    renderIdle();
    return;
  }
  if (!state.rows.length) {
    el.results.innerHTML = R.emptyDataset({ error: state.dataset && state.dataset.error });
    return;
  }

  el.results.innerHTML = R.loading('Looking…');
  let response;
  try {
    response = await getLookup(clean);
  } catch (err) {
    el.results.innerHTML = R.loadError({ message: err.message });
    return;
  }
  state.lastResponse = response;
  renderResponse(response);
}

/** The straight answer: solved/wanted/rejected cards, or the miss panel. */
function renderResponse(res) {
  const q = res.query || {};
  const now = new Date();
  const voted = state.votes;
  const rows = (res.rows || []).map(normalizeRow);
  const context = (res.context || []).map(normalizeRow);

  const answers = rows.filter((r) => r.model_family !== '*');
  const hardwareLevel = rows.filter((r) => r.model_family === '*');
  // With no model asked for, a hardware-level row IS an answer to "does this
  // card work at all"; with a model asked for it stays context and is never
  // counted as an answer (§3).
  const askedModel = Boolean(q.model);

  const parts = [];

  // head line — the counts here must agree with the miss counters and the
  // "related rows" chips; all three derive from the same response.
  const headline = [q.hw, q.model, q.runtime].filter(Boolean).join(' × ') || 'all rows';
  const hlCount = hardwareLevel.length + context.length;
  const countText = res.miss
    ? `no model-specific claim${hlCount ? ` · ${hlCount} hardware-level` : ''}`
    : askedModel
      ? `${answers.length} model-specific ${answers.length === 1 ? 'claim' : 'claims'}${hlCount ? ` · ${hlCount} hardware-level` : ''}`
      : `${answers.length + hlCount} hardware-level ${answers.length + hlCount === 1 ? 'claim' : 'claims'} — none for a specific model`;
  parts.push(`<div class="results-head">
    <h2>${R.esc(headline)}</h2>
    <span class="count">${R.esc(countText)}</span>
    <span class="spacer"></span>
    <button type="button" class="btn btn-ghost btn-sm" data-copy-link>Copy link</button>
    <button type="button" class="btn btn-ghost btn-sm" data-reveal-json>Show JSON</button>
  </div>`);

  const apiMode = state.source === 'api';
  if (res.miss) {
    // THE deciding surface.
    const payload = missPayload(res);
    parts.push(R.missPanel(res, { now, payload, apiMode }));
    if (context.length) {
      parts.push(R.contextSection(context, { now, voted, apiMode, heading: 'Hardware-level support for this card' }));
    }
    parts.push(R.neighbouringNote(relatedRows(res), q));
  } else {
    const groups = SR.groupVariants
      ? SR.groupVariants(answers)
      : answers.map((r) => ({ parent: r, variants: [] }));
    const cardsHtml = R.cardGroup
      ? groups.map((g) => R.cardGroup(g, { now, voted, apiMode })).join('')
      : answers.map((r) => R.cardFor(r, { now, voted, apiMode })).join('');
    parts.push(`<div class="cards">${cardsHtml}</div>`);
    // Hardware-level rows always render in their own clearly-labelled section,
    // never mixed in with model answers. One list, deduped by id: with no model
    // asked they arrive in `rows`; with a model asked they arrive in `context`.
    const hlRows = [...hardwareLevel, ...context].filter(
      (r, i, arr) => arr.findIndex((x) => x.id === r.id) === i
    );
    if (hlRows.length) {
      parts.push(
        R.contextSection(hlRows, {
          now,
          voted,
          heading: askedModel ? 'Hardware-level support for this card' : 'Hardware-level support — what these rows claim'
        })
      );
    }
    if (!answers.length && !hlRows.length) {
      parts.push(`<p class="section-note">No rows matched. Clear a field to widen the query.</p>`);
    }
  }

  parts.push(`<details class="details-row" data-json-details style="margin-top:18px">
    <summary>Raw response JSON — same shape as GET /api/lookup</summary>
    <div class="details-body"><pre tabindex="0" data-json class="json-pre" style="padding:11px;overflow:auto;max-height:320px">${R.esc(JSON.stringify(slim(res), null, 2))}</pre></div>
  </details>`);

  el.results.innerHTML = parts.join('');
  el.results.querySelector('.miss')?.focus({ preventScroll: true });
  announce(res.miss ? `Miss: ${res.miss.reason}. ${R.esc('')}` : `${answers.length} claims found`);
}

/** Rows for the "related" hint under a miss: same hw, any model. */
/**
 * Rows to offer under a miss — "here is what does exist for this card".
 *
 * Deliberately computed with the SAME `lookup()` and the same query as the miss
 * itself, never with an ad-hoc substring check: the chips and the counters must
 * always agree. If the counters say "hardware-level claims: 1", exactly the rows
 * behind that 1 are offered here.
 */
function relatedRows(res) {
  const q = res.query || {};
  if (!(q.hw || q.model || q.runtime)) return [];

  const list = new Map();
  // 1) hardware-level context returned with this very response
  for (const r of res.context || []) list.set(r.id, normalizeRow(r));
  // 2) anything the same card answers for a different model (the qwen3-style rows)
  if (q.hw) {
    const siblings = lookup(state.rows, { hw: q.hw, limit: 50 }, state.dataset, state.taxonomy);
    for (const r of siblings.rows || []) if (r.model_family !== '*') list.set(r.id, r);
    for (const r of siblings.context || []) list.set(r.id, r);
  }

  const rank = { wanted: 0, solved: 1, rejected: 2 };
  return [...list.values()]
    .sort((a, b) => (rank[a.status] ?? 3) - (rank[b.status] ?? 3) || String(a.model_family).localeCompare(String(b.model_family)))
    .slice(0, 8);
}

/** What gets shown as "the JSON" for a lookup — the CONTRACT §4 object, nothing internal. */
function slim(res) {
  const out = {
    query: res.query,
    rows: res.rows,
    context: res.context,
    miss: res.miss,
    query_id: res.query_id,
    generated_at: res.generated_at,
    dataset: res.dataset
  };
  return out;
}

/** The payload the miss panel offers to copy — exactly CONTRACT §4. */
function missPayload(res) {
  const q = res.query || {};
  return {
    query: q,
    rows: [],
    context: (res.context || []).map((r) => r.id),
    miss: res.miss,
    query_id: res.query_id,
    generated_at: res.generated_at,
    dataset: res.dataset,
    id: idFor(q)
  };
}

function announce(msg) {
  if (el.status) el.status.textContent = msg;
}

function renderIdle() {
  const ds = state.dataset || {};
  el.results.innerHTML = `<section class="empty-state" style="margin-top:18px">
    <h2>Start with a combination</h2>
    <p>Fill in any one of the three fields — none are required, and any subset works. Type an architecture,
    a model family, or pick a runtime, then press <kbd>Enter</kbd>.</p>
    <p style="color:var(--ink-3);font-size:var(--step--1)">
      The index currently holds <strong>${R.esc(ds.rows ?? 0)}</strong> claims, as of
      <strong>${R.esc(ds.as_of || 'an unknown date')}</strong>.
    </p>
  </section>`;
}

/* -------------------------------------------------------------- deep link */

function writeHash(q, view) {
  const params = new URLSearchParams();
  for (const k of ['hw', 'model', 'runtime']) if (q[k]) params.set(k, q[k]);
  const hash = params.toString() ? `${view}?${params}` : view;
  if (location.hash.replace(/^#/, '') !== hash) {
    history.pushState(null, '', `#${hash}`);
  }
}

function syncFormFromHash() {
  const params = readHashQuery();
  el.hw.value = params.get('hw') || '';
  el.model.value = params.get('model') || '';
  const rt = params.get('runtime') || '';
  if (rt && ![...el.runtime.options].some((o) => o.value === rt)) {
    // A runtime the dataset does not list (e.g. ?runtime=llama_cpp on an empty
    // index): keep it reachable instead of silently dropping it.
    const opt = document.createElement('option');
    opt.value = rt;
    opt.textContent = rt;
    el.runtime.append(opt);
  }
  el.runtime.value = rt;
  syncClearButtons();
}

function writeBrowseHash({ replace = false } = {}) {
  const b = state.browse;
  const params = new URLSearchParams();
  if (b.status) params.set('status', b.status);
  if (b.q) params.set('q', b.q);
  if (b.sort && b.sort !== 'status') params.set('sort', b.sort);
  if (b.dir && b.dir !== 'desc') params.set('dir', b.dir);
  const hash = params.toString() ? `browse?${params}` : 'browse';
  if (location.hash.replace(/^#/, '') !== hash) {
    if (replace) history.replaceState(null, '', `#${hash}`);
    else history.pushState(null, '', `#${hash}`);
  }
}

function syncBrowseFromHash() {
  const params = readHashQuery();
  state.browse.status = params.get('status') || '';
  state.browse.q = params.get('q') || '';
  state.browse.sort = params.get('sort') || 'status';
  state.browse.dir = params.get('dir') || 'desc';
  if (el.browseQ) el.browseQ.value = state.browse.q;
  const toolbar = $('#browse-toolbar');
  if (toolbar) {
    $$('[data-filter-status]', toolbar).forEach((c) =>
      c.setAttribute('aria-pressed', String((c.dataset.filterStatus || '') === state.browse.status))
    );
  }
  const sortSel = $('#browse-sort');
  if (sortSel) {
    sortSel.value = state.browse.sort === 'as_of' && state.browse.dir === 'asc' ? 'as_of_old' : state.browse.sort;
  }
}

async function route() {
  const view = routeView();
  setView(view, { silent: true });
  if (view === 'browse') {
    syncBrowseFromHash();
    await renderBrowse();
    return;
  }
  syncFormFromHash();
  const params = readLookupParams();
  const q = buildQuery(params);
  if (isBlank(q)) {
    renderIdle();
    return;
  }
  await performLookup(q, { push: false });
}

/* ----------------------------------------------------------------- browse */

async function renderBrowse() {
  const b = state.browse;
  const all = state.rows;
  let rows = all;

  // Coverage at a glance: vendor x count strip
  if (el.browseCoverage) {
    const vCounts = new Map();
    for (const r of all) {
      if (!r.hw_vendor) continue;
      vCounts.set(r.hw_vendor, (vCounts.get(r.hw_vendor) || 0) + 1);
    }
    const vendors = [...vCounts.entries()].sort((a, b2) => b2[1] - a[1] || a[0].localeCompare(b2[0]));
    if (vendors.length) {
      el.browseCoverage.hidden = false;
      el.browseCoverage.innerHTML = `<span class="coverage-label">Coverage:</span>` +
        vendors.map(([v, c]) =>
          `<button type="button" class="chip" data-filter-vendor="${R.esc(v)}" aria-pressed="${b.vendor === v ? 'true' : 'false'}">${R.esc(v)} <span class="n">${R.esc(c)}</span></button>`
        ).join('');
      el.browseCoverage.querySelectorAll('[data-filter-vendor]').forEach((btn) => {
        btn.addEventListener('click', () => {
          b.vendor = b.vendor === btn.dataset.filterVendor ? '' : btn.dataset.filterVendor;
          renderBrowse();
        });
      });
    } else {
      el.browseCoverage.hidden = true;
    }
  }

  if (b.status === 'context') rows = rows.filter((r) => r.model_family === '*');
  else if (b.status === 'untested' || b.status === 'wanted') {
    rows = rows.filter((r) => r.model_family !== '*' && (r.status === 'untested' || r.status === 'wanted'));
  } else if (b.status) rows = rows.filter((r) => r.model_family !== '*' && r.status === b.status);

  if (b.vendor) {
    rows = rows.filter((r) => r.hw_vendor === b.vendor);
  }

  if (b.q) {
    const needle = b.q.toLowerCase();
    rows = rows.filter((r) =>
      [r.id, r.hw_vendor, r.hw_arch, r.hw_name, r.model_family, r.runtime, r.runtime_rev, r.quant, r.status, r.source_kind, r.notes]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(needle)
    );
  }

  rows = sortBrowse(rows, b.sort, b.dir);

  el.browseMeta.innerHTML = `<span><strong>${rows.length}</strong> of ${all.length} rows</span>` +
    (b.status || b.vendor || b.q ? ` <button type="button" class="chip" data-filter-status="" style="min-height:26px;padding:2px 10px">clear filters</button>` : '');
  el.browseResults.innerHTML = R.browseTable(rows, {
    sort: b.sort,
    dir: b.dir,
    now: new Date(),
    voted: state.votes,
    total: all.length,
    statusFilter: b.status,
    apiMode: state.source === 'api'
  });
  const goLookup = el.browseResults.querySelector('[data-go-lookup]');
  if (goLookup) {
    goLookup.addEventListener('click', () => {
      setView('lookup');
      if (el.hw) el.hw.focus();
    });
  }
}

function sortBrowse(rows, key, dir) {
  const rank = { untested: 0, wanted: 0, solved: 1, rejected: 2 };
  const val = (r) => {
    switch (key) {
      case 'status':
        return rank[r.model_family === '*' ? 'context' : r.status] ?? 3;
      case 'hw_vendor':
        return `${r.hw_vendor}`;
      case 'hw_arch':
        return `${r.hw_arch}`;
      case 'model_family':
        return `${r.model_family}`;
      case 'runtime':
        return `${r.runtime}`;
      case 'as_of':
        return `${r.as_of}`;
      case 'as_of_old':
        return `${r.as_of}`;
      case 'want_votes':
        return r.want_votes || 0;
      case 'source_kind':
        return `${r.source_kind}`;
      default:
        return `${r.id}`;
    }
  };
  const numeric = key === 'want_votes' || key === 'status';
  const sign = key === 'as_of_old' ? -1 : dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = val(a);
    const vb = val(b);
    let c;
    if (numeric) c = va - vb;
    else c = String(va).localeCompare(String(vb));
    if (c) return c * sign;
    // Wanted: votes desc then want_first asc (CONTRACT), inside any sort.
    if (a.status === 'wanted' && b.status === 'wanted') {
      const dv = (b.want_votes || 0) - (a.want_votes || 0);
      if (dv) return dv;
      return String(a.want_first || '').localeCompare(String(b.want_first || ''));
    }
    return String(a.id).localeCompare(String(b.id));
  });
}

/* ---------------------------------------------------------------- combobox */

/**
 * A searchable listbox over the facets. Kept small and accessible: real
 * aria-activedescendant, Enter to accept, Escape to close, Tab to leave.
 */
function setupCombobox(input, list, optionsFor) {
  let items = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  };

  const open = () => {
    items = optionsFor(input.value.trim());
    if (!items.length) {
      list.innerHTML = `<div class="combo-empty">No match. You can type a value and press Enter anyway — an unmatched value is how you find a gap.</div>`;
    } else {
      let html = '';
      let lastGroup = null;
      for (const it of items) {
        if (it.group && it.group !== lastGroup) {
          html += `<div class="combo-group-label" role="presentation">${R.esc(it.group)}</div>`;
          lastGroup = it.group;
        }
        html += `<button type="button" class="combo-opt" role="option" id="${list.id}-o${it.i}" aria-selected="false" data-value="${R.esc(it.value)}">
          <span class="opt-main">${R.esc(it.label)}</span>${it.sub ? `<span class="opt-sub">${R.esc(it.sub)}</span>` : ''}
          ${it.count ? `<span class="opt-count">${it.count}</span>` : ''}
        </button>`;
      }
      list.innerHTML = html;
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    active = -1;
  };

  const setActive = (i) => {
    const opts = $$('.combo-opt[role="option"]', list);
    if (!opts.length) return;
    active = Math.max(0, Math.min(i, opts.length - 1));
    opts.forEach((o, idx) => o.setAttribute('aria-selected', String(idx === active)));
    const cur = opts[active];
    input.setAttribute('aria-activedescendant', cur.id);
    cur.scrollIntoView({ block: 'nearest' });
  };

  const choose = (i) => {
    const opts = $$('.combo-opt[role="option"]', list);
    if (!opts[i]) return false;
    input.value = opts[i].dataset.value;
    syncClearButtons();
    close();
    performLookup(currentQuery(), { push: true });
    return true;
  };

  input.addEventListener('input', () => {
    syncClearButtons();
    open();
    // Live filter: once all three fields are decided, update results as you type.
    debouncedLookup();
  });

  input.addEventListener('focus', () => {
    if (!input.value) open();
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (list.hidden) open();
      setActive(active + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (list.hidden) open();
      setActive(active - 1);
    } else if (e.key === 'Enter') {
      if (!list.hidden && active >= 0) {
        e.preventDefault();
        e.stopPropagation();
        choose(active);
      }
      // otherwise let the form submit
    } else if (e.key === 'Escape') {
      // first Escape closes the list only — a second clears (handled globally)
      if (!list.hidden) {
        e.preventDefault();
        e.stopPropagation();
        close();
      }
    } else if (e.key === 'Tab') {
      close();
    }
  });

  list.addEventListener('mousedown', (e) => e.preventDefault()); // keep focus in input
  list.addEventListener('click', (e) => {
    const opt = e.target.closest('.combo-opt[role="option"]');
    if (opt) choose([...$$('.combo-opt[role="option"]', list)].indexOf(opt));
  });

  document.addEventListener('click', (e) => {
    if (!list.hidden && !list.contains(e.target) && e.target !== input) close();
  });
  input.addEventListener('blur', () => setTimeout(() => {
    if (!list.matches(':hover')) close();
  }, 120));

  return { close, open };
}

function hwOptions(fieldText) {
  if (!state.facets) return [];
  const needle = fieldText.toLowerCase();
  const compactNeedle = compactIdToken(fieldText);
  const out = [];
  const seen = new Set();
  let i = 0;

  // Match hardware aliases from taxonomy when typing
  const aliasMatches = new Map();
  if (needle && state.taxonomy && state.taxonomy.hw_aliases) {
    for (const [alias, target] of Object.entries(state.taxonomy.hw_aliases)) {
      if (alias.toLowerCase().includes(needle) || (compactNeedle && compactIdToken(alias).includes(compactNeedle))) {
        if (!aliasMatches.has(target)) aliasMatches.set(target, alias);
      }
    }
  }

  for (const v of state.facets.vendors) {
    if (needle) {
      const vendorHit = v.value.includes(needle) || v.label.toLowerCase().includes(needle);
      for (const a of v.arches) {
        const aliasHit = aliasMatches.get(a.value);
        if (vendorHit || a.value.includes(needle) || a.label.toLowerCase().includes(needle) || aliasHit) {
          seen.add(a.value);
          const sub = aliasHit ? `${a.label} (alias: ${aliasHit})` : a.label;
          out.push({ i: i++, group: v.label, value: a.value, label: a.value, sub, count: a.count });
        }
      }
    } else {
      // grouped by vendor (task: hardware is grouped by vendor, shows hw_name)
      for (const a of v.arches) {
        seen.add(a.value);
        out.push({ i: i++, group: v.label, value: a.value, label: a.value, sub: a.label, count: a.count });
      }
    }
  }
  for (const [target, alias] of aliasMatches.entries()) {
    if (!seen.has(target)) {
      seen.add(target);
      out.push({ i: i++, group: 'Alias match', value: target, label: target, sub: `alias: ${alias}`, count: 0 });
    }
  }
  // Also offer the vendor itself as an option (a wider query).
  if (!needle) {
    for (const v of state.facets.vendors) {
      out.push({ i: i++, group: 'Whole vendor', value: v.value, label: v.label, sub: 'all arches', count: v.count });
    }
  }
  return out.slice(0, 60);
}

function modelOptions(fieldText) {
  if (!state.facets) return [];
  const needle = fieldText.toLowerCase();
  const compactNeedle = compactIdToken(fieldText);
  const aliasMatches = new Map();
  if (needle && state.taxonomy && Array.isArray(state.taxonomy.models)) {
    for (const m of state.taxonomy.models) {
      const aliases = Array.isArray(m.aliases) ? m.aliases : [];
      const hit = aliases.find((al) => al.toLowerCase().includes(needle) || (compactNeedle && compactIdToken(al).includes(compactNeedle)));
      if (hit && !aliasMatches.has(m.family)) aliasMatches.set(m.family, hit);
    }
  }
  const seen = new Set();
  const out = [];
  let i = 0;
  for (const m of state.facets.models) {
    const aliasHit = aliasMatches.get(m.value);
    if (!needle || m.value.toLowerCase().includes(needle) || aliasHit) {
      seen.add(m.value);
      out.push({ i: i++, value: m.value, label: m.value, sub: aliasHit ? `alias: ${aliasHit}` : '', count: m.count });
    }
  }
  for (const [family, alias] of aliasMatches.entries()) {
    if (!seen.has(family)) {
      seen.add(family);
      out.push({ i: i++, value: family, label: family, sub: `alias: ${alias}`, count: 0 });
    }
  }
  return out.slice(0, 40);
}

/* --------------------------------------------------------------- events */

const debounce = (fn, ms) => {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
};
const debouncedLookup = debounce(() => {
  const q = currentQuery();
  if (isBlank(q)) return;
  performLookup(q, { push: true });
}, 320);

function syncClearButtons() {
  $$('[data-clear]').forEach((b) => {
    b.hidden = !$(`#${b.dataset.clear}-input`).value;
  });
}

function bindEvents() {
  const hwCombo = setupCombobox(el.hw, el.hwList, hwOptions);
  const modelCombo = setupCombobox(el.model, el.modelList, modelOptions);
  el.hw._openList = hwCombo.open;
  el.model._openList = modelCombo.open;

  $$('[data-clear]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = $(`#${btn.dataset.clear}-input`);
      input.value = '';
      syncClearButtons();
      input.focus();
      performLookup(currentQuery(), { push: true });
    });
  });

  el.runtime.addEventListener('change', () => performLookup(currentQuery(), { push: true }));

  el.form.addEventListener('submit', (e) => {
    e.preventDefault();
    hwCombo.close();
    modelCombo.close();
    performLookup(currentQuery(), { push: true });
  });

  $('#clear-all').addEventListener('click', () => {
    clearAll();
  });

  $('#copy-link').addEventListener('click', () => copyLink());

  $$('[data-nav]').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const view = a.dataset.nav;
      if (view === 'browse') {
        location.hash = 'browse';
      } else {
        const q = currentQuery();
        const params = new URLSearchParams();
        for (const k of ['hw', 'model', 'runtime']) if (q[k]) params.set(k, q[k]);
        location.hash = params.toString() ? `lookup?${params}` : 'lookup';
      }
    });
  });

  $('[data-home]').addEventListener('click', (e) => {
    e.preventDefault();
    clearAll();
    location.hash = 'lookup';
  });

  // browse controls
  document.addEventListener('click', (e) => {
    const chip = e.target.closest('[data-filter-status]');
    if (chip && $('#browse-toolbar').contains(chip)) {
      state.browse.status = chip.dataset.filterStatus || '';
      $$('[data-filter-status]', $('#browse-toolbar')).forEach((c) =>
        c.setAttribute('aria-pressed', String((c.dataset.filterStatus || '') === state.browse.status))
      );
      writeBrowseHash();
      renderBrowse();
      return;
    }
    const sortBtn = e.target.closest('[data-sort]');
    if (sortBtn) {
      state.browse.sort = sortBtn.dataset.sort;
      state.browse.dir = sortBtn.dataset.dir;
      writeBrowseHash();
      renderBrowse();
      return;
    }
    const openRow = e.target.closest('[data-open-row]');
    if (openRow) {
      openRowAsLookup(openRow.dataset.openRow);
      return;
    }
    // results-area actions
    const voteBtn = e.target.closest('[data-vote]');
    if (voteBtn) {
      handleVote(voteBtn);
      return;
    }
    if (e.target.closest('[data-want-miss]')) {
      handleWantMiss(e.target.closest('[data-want-miss]'));
      return;
    }
    if (e.target.closest('[data-copy-payload]')) {
      copyPayload(e.target.closest('[data-copy-payload]'));
      return;
    }
    if (e.target.closest('[data-download-payload]')) {
      downloadPayload();
      return;
    }
    if (e.target.closest('[data-copy-link]')) {
      copyLink();
      return;
    }
    if (e.target.closest('[data-copy-id]')) {
      copyText(e.target.closest('[data-copy-id]').dataset.copyId, 'Row id copied');
      return;
    }
    if (e.target.closest('[data-link-row]')) {
      linkRow(e.target.closest('[data-link-row]').dataset.linkRow);
      return;
    }
    if (e.target.closest('[data-copy-snippet]')) {
      copyText($('#agent-snippet').textContent.replace('Copy', '').trim(), 'Agent snippet copied');
      return;
    }
    if (e.target.closest('[data-reveal-json]')) {
      const d = $('[data-json-details]');
      if (d) {
        d.open = true;
        d.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
      return;
    }
    const starter = e.target.closest('[data-starter]');
    if (starter) {
      try {
        const q = JSON.parse(starter.dataset.starter);
        el.hw.value = q.hw || '';
        el.model.value = q.model || '';
        el.runtime.value = q.runtime || '';
        syncClearButtons();
        performLookup(currentQuery(), { push: true });
      } catch {
        /* ignore */
      }
      return;
    }
    const tryHw = e.target.closest('[data-try-hw]');
    if (tryHw) {
      el.hw.value = tryHw.dataset.tryHw;
      el.model.value = '';
      el.runtime.value = tryHw.dataset.tryRuntime || '';
      syncClearButtons();
      performLookup(currentQuery(), { push: true });
      return;
    }

  });

  el.browseQ.addEventListener(
    'input',
    debounce(() => {
      state.browse.q = el.browseQ.value.trim();
      writeBrowseHash({ replace: true });
      renderBrowse();
    }, 160)
  );

  $('#browse-sort').addEventListener('change', (e) => {
    const v = e.target.value;
    if (v === 'as_of_old') {
      state.browse.sort = 'as_of';
      state.browse.dir = 'asc';
    } else {
      state.browse.sort = v;
      state.browse.dir = 'desc';
    }
    writeBrowseHash();
    renderBrowse();
  });

  $('#theme-toggle').addEventListener('click', () => {
    const root = document.documentElement;
    const cur = root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try {
      localStorage.setItem('solve.run.theme', next);
    } catch {
      /* ignore */
    }
  });
  try {
    const t = localStorage.getItem('solve.run.theme');
    if (t) document.documentElement.dataset.theme = t;
  } catch {
    /* ignore */
  }

  // ---- global keyboard -----------------------------------------------------
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    const typing = tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable;

    // "/" focuses search from anywhere that isn't already a field.
    if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
      if (state.view !== 'lookup') {
        location.hash = 'lookup';
        requestAnimationFrame(() => el.hw.focus());
      } else {
        e.preventDefault();
        el.hw.focus();
        el.hw.select();
        // `/` is an invitation to type: show what there is to pick from.
        el.hw._openList?.();
      }
      return;
    }

    // Escape: close lists first (handled by combobox), else clear the lookup.
    if (e.key === 'Escape') {
      if (typing) return; // field-level Escape handled above / native
      if (state.view !== 'lookup') return;
      const q = currentQuery();
      if (!isBlank(q)) {
        clearAll();
        toast('Cleared');
      }
      return;
    }

    // Arrow keys move focus through result cards (not while typing).
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'j' || e.key === 'k') && !typing && !e.metaKey && !e.ctrlKey) {
      const cards = $$('.card, .miss', el.results);
      if (!cards.length) return;
      const idx = cards.indexOf(document.activeElement);
      if (idx === -1 && (e.key === 'ArrowDown' || e.key === 'j')) {
        e.preventDefault();
        cards[0].focus();
        return;
      }
      if (idx === -1) return;
      e.preventDefault();
      const next = e.key === 'ArrowDown' || e.key === 'j' ? idx + 1 : idx - 1;
      if (next >= 0 && next < cards.length) cards[next].focus();
    }

    // "w" votes on the focused wanted card.
    if ((e.key === 'w' || e.key === 'W') && !typing && !e.metaKey && !e.ctrlKey) {
      const card = document.activeElement?.closest?.('.card[data-state="wanted"]');
      if (card) {
        const btn = card.querySelector('[data-vote]');
        if (btn) {
          e.preventDefault();
          handleVote(btn);
        }
      }
    }
  });

  window.addEventListener('hashchange', route);
  window.addEventListener('popstate', route);

  // Refresh the dataset when the page becomes visible again after a while.
  let lastShown = Date.now();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && Date.now() - lastShown > 5 * 60 * 1000) {
      clearStaticCache();
      loadData().then(() => route());
    }
    if (document.visibilityState === 'visible') lastShown = Date.now();
  });
}

/* ---------------------------------------------------------------- actions */

function clearAll() {
  el.hw.value = '';
  el.model.value = '';
  el.runtime.value = '';
  syncClearButtons();
  history.pushState(null, '', '#lookup');
  renderIdle();
  el.hw.focus();
}

function copyLink() {
  const q = currentQuery();
  const params = new URLSearchParams();
  for (const k of ['hw', 'model', 'runtime']) if (q[k]) params.set(k, q[k]);
  const hash = params.toString() ? `lookup?${params}` : 'lookup';
  const url = `${location.origin}${location.pathname}#${hash}`;
  copyText(url, 'Link copied — it opens this exact lookup');
}

function linkRow(id) {
  // Find the row and express it as a plain lookup (hw+runtime+model), which is
  // what the URL form supports; a model-less row links its hw + runtime.
  const row = state.rows.find((r) => r.id === id);
  if (!row) return;
  el.hw.value = row.hw_arch;
  el.model.value = row.model_family === '*' ? '' : row.model_family;
  el.runtime.value = row.runtime;
  syncClearButtons();
  performLookup(currentQuery(), { push: true });
  toast('Linked to this row');
}

function openRowAsLookup(id) {
  const row = state.rows.find((r) => r.id === id);
  if (!row) return;
  el.hw.value = row.hw_arch;
  el.model.value = row.model_family === '*' ? '' : row.model_family;
  el.runtime.value = row.runtime;
  syncClearButtons();
  location.hash = '#lookup';
  setView('lookup');
  performLookup(currentQuery(), { push: true });
}

async function handleVote(btn) {
  const id = btn.dataset.vote;
  if (state.votes.has(id)) {
    toast('You already voted for this');
    btn.dataset.voted = 'true';
    btn.setAttribute('aria-pressed', 'true');
    return;
  }
  const row = state.rows.find((r) => r.id === id);
  const before = row ? row.want_votes || 0 : 0;

  btn.disabled = true;
  const res = await voteFor(id, { extra: { voter: voterKey() } });
  btn.disabled = false;

  const card = btn.closest('.card');
  const countEl = card && card.querySelector('.vote-count .n');

  if (res.ok) {
    state.votes.add(id);
    saveVoted();
    const nextCount = typeof res.votes === 'number' ? res.votes : before + 1;
    if (row) row.want_votes = nextCount;
    if (countEl) countEl.textContent = String(nextCount);
    btn.dataset.voted = 'true';
    btn.setAttribute('aria-pressed', 'true');
    const label = btn.querySelector('.vote-label');
    if (label) label.textContent = 'Voted';
    toast('Wanted — vote counted');
  } else {
    toast('The vote service is unreachable right now.');
    const live = card && card.querySelector('.feedback');
    if (live) {
      live.dataset.tone = 'bad';
      live.textContent = 'vote not recorded — ' + (res.error || 'offline');
    }
  }
}

async function handleWantMiss(btn) {
  const id = btn.dataset.id;
  const res = state.lastResponse;
  btn.disabled = true;
  const fb = el.results.querySelector('[data-miss-feedback]');
  const voteRes = await voteFor(id, { extra: { voter: voterKey() } });
  let reported = false;
  if (res) {
    const rep = await reportMiss({ query: res.query, searcher_key: voterKey() });
    reported = rep.ok;
  }
  btn.disabled = false;

  if (voteRes.ok || reported) {
    btn.setAttribute('aria-pressed', 'true');
    btn.querySelector('.vote-label').textContent = 'Wanted ✓';
    if (fb) {
      fb.dataset.tone = 'ok';
      fb.textContent = reported
        ? 'Thanks — the miss is logged. At 3 distinct searchers an auto-wanted row is created.'
        : 'Vote recorded. (Miss log unavailable in this hosting mode.)';
    }
    toast('Wanted it — this gap is on record now');
  } else {
    if (fb) {
      fb.dataset.tone = 'bad';
      fb.textContent =
        'Not saved: this hosting mode is read-only, so the vote stays in this browser. Run the site with scripts/serve.py to record it.';
    }
  }
}

function copyPayload(trigger) {
  const res = state.lastResponse;
  if (!res) return;
  copyText(JSON.stringify(missPayload(res), null, 2), 'Miss report copied — paste it into the issue or agent');
}

function downloadPayload() {
  const res = state.lastResponse;
  if (!res) return;
  const blob = new Blob([JSON.stringify(missPayload(res), null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `miss-${res.query_id || 'lookup'}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ------------------------------------------------------------------- boot */
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

// exported for tests / debugging

  Object.assign(SR, { state, currentQuery, renderResponse, sortBrowse });
})(window.__SR = window.__SR || {});
