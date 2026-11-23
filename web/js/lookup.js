/* lookup.js — classic script build (see web/tools/to-classic.mjs).
   Loaded in order from index.html so the site also works from file://,
   where browsers block ES modules and fetch(). Source of truth is this file. */
(function (SR) {
'use strict';
/**
 * lookup.js — PURE matching library. No DOM, no network, no imports.
 *
 * Mirrors CONTRACT.md §4 (query params, matching, miss payload) so the static
 * site gives the same answer as api/lookup.py. Never `fetch` from here: this
 * module is the thing the tests assert against, so it must be a function of its
 * arguments only.
 *
 *   import { lookup, MISS_REASONS, buildQuery } from './lookup.js';
 *   lookup(rows, { hw: 'sm_86', model: 'qwen3' }, dataset) -> response object
 */

const MISS_REASONS = Object.freeze([
  'no-claim',
  'untested-only',
  'rejected-only',
  'partial-context',
  'no-match'
]);

const STATUSES = Object.freeze(['solved', 'untested', 'rejected']);
const SOURCE_KINDS = Object.freeze(['scraped', 'derived', 'hand', 'author-claim']);

const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 500;

/* ------------------------------------------------------------------ utils */

const lower = (v) => (typeof v === 'string' ? v.toLowerCase() : '');

/** Empty / whitespace-only / nullish params are "not supplied". */
function cleanParam(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  if (!s) return null;
  return s;
}

function slug(s) {
  return lower(s)
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * Slug used for ids and for want/miss endpoints. CONTRACT §2: dots are not
 * allowed inside id segments, so `llama.cpp` becomes `llama-cpp` as a *key*
 * while the display slug stays `llama.cpp`.
 */
function keyify(s) {
  return slug(s).replace(/\./g, '-');
}

/** Deterministic 8-hex query id (FNV-1a), so the same query pastes the same. */
function hash8(s) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0').slice(0, 8);
}

/* ------------------------------------------------------- normalization */

/**
 * Accept rows in any of the tolerated container shapes:
 *   - a plain array of rows
 *   - {rows: [...]}                     (combos.json v1 as written by pipeline)
 *   - JSONL text  (api/export.jsonl / data/combos.jsonl, one row per line)
 * Returns {rows, dataset}. Extra per-row tolerances mirror the validator's
 * optional-field defaults so the UI never crashes on a minimal row.
 */
function normalizeData(input, datasetHint) {
  let rows = [];
  let dataset = datasetHint || null;

  if (typeof input === 'string') {
    rows = input
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => JSON.parse(l));
  } else if (Array.isArray(input)) {
    rows = input;
  } else if (input && Array.isArray(input.rows)) {
    rows = input.rows;
    if (input.dataset) dataset = { ...dataset, ...input.dataset };
    if (input.generated_at) dataset = { ...dataset, generated_at: input.generated_at };
    if (input.source) dataset = { ...dataset, source: input.source };
  } else if (input && Array.isArray(input.combos)) {
    rows = input.combos;
  } else if (input && typeof input === 'object' && String(input.id || '').includes('/')) {
    rows = [input];
  } else if (input != null) {
    throw new Error('Unrecognised dataset shape: expected an array of rows or {"rows": [...]}');
  }

  rows = rows.filter((r) => r && typeof r === 'object' && r.id).map(normalizeRow);
  return { rows, dataset: dataset || datasetFromRows(rows) };
}

/** Fill CONTRACT optional fields with their documented defaults. */
function normalizeRow(row) {
  const r = { ...row };
  if (!Array.isArray(r.evidence)) r.evidence = [];
  if (!Array.isArray(r.missing)) r.missing = [];
  if (!Array.isArray(r.want_requesters)) r.want_requesters = [];
  if (typeof r.want_votes !== 'number' || !Number.isFinite(r.want_votes)) {
    r.want_votes = Number(r.want_votes) || 0;
  }
  if (r.hw_extra == null || typeof r.hw_extra !== 'object') r.hw_extra = {};
  if (r.pointer_alive === undefined) r.pointer_alive = true;
  if (r.status === 'solved' && !r.pointer) r.status = 'untested'; // never render a solved row with nowhere to go
  return r;
}

/** Derive dataset meta from rows when the file does not carry it. */
function datasetFromRows(rows, extra) {
  const dated = rows.map((r) => r.as_of).filter(isDate).sort();
  return {
    rows: rows.length,
    as_of: dated.length ? dated[dated.length - 1] : null,
    version: null,
    ...(extra || {})
  };
}

function isDate(v) {
  return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v);
}

/* ------------------------------------------------------------ query */

/**
 * Pull the CONTRACT §4 query out of a URLSearchParams, a plain object or the
 * current location. Unknown params are dropped (CONTRACT: "unknown params
 * ignored"). `hw` accepts `hw_arch` so ?hw_arch=sm_86 links keep working.
 */
function buildQuery(src) {
  let get;
  if (src instanceof URLSearchParams) get = (k) => src.get(k);
  else {
    const o = src || {};
    get = (k) => (o[k] === undefined || o[k] === null ? null : String(o[k]));
  }
  const hw = cleanParam(get('hw_arch')) || cleanParam(get('hw'));
  const kind = cleanParam(get('kind')) || cleanParam(get('source_kind'));
  let limit = parseInt(cleanParam(get('limit')) || '', 10);
  if (!Number.isFinite(limit) || limit <= 0) limit = DEFAULT_LIMIT;
  limit = Math.min(limit, MAX_LIMIT);

  const q = {
    hw,
    model: cleanParam(get('model')) || cleanParam(get('model_family')),
    runtime: cleanParam(get('runtime')),
    status: cleanParam(get('status')),
    kind,
    q: cleanParam(get('q')) || cleanParam(get('search')),
    limit
  };
  if (q.status && !STATUSES.includes(q.status)) q.status = null;
  if (q.kind && !SOURCE_KINDS.includes(q.kind)) q.kind = null;
  return q;
}

/**
 * Loose comparison form — the SAME rule as api/store.py `norm_token`, so a query
 * answered by /api/lookup and the same query answered statically agree:
 * lowercase, dots / underscores / whitespace collapsed to '-' (runs collapsed).
 */
function normToken(s) {
  return (s === null || s === undefined ? '' : String(s))
    .trim()
    .toLowerCase()
    .replace(/[._\s/]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function compactToken(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function buildAliasIndex(taxonomy) {
  if (taxonomy && taxonomy.hw instanceof Map && taxonomy.model instanceof Map) {
    return taxonomy;
  }
  const hw = new Map();
  const model = new Map();
  if (taxonomy && taxonomy.hw_aliases && typeof taxonomy.hw_aliases === 'object') {
    for (const [alias, arch] of Object.entries(taxonomy.hw_aliases)) {
      if (!alias || !arch) continue;
      const canon = String(arch);
      const nk = normToken(alias);
      const ck = compactToken(alias);
      if (nk && !hw.has(nk)) hw.set(nk, canon);
      if (ck && !hw.has(ck)) hw.set(ck, canon);
    }
  }
  if (taxonomy && Array.isArray(taxonomy.models)) {
    for (const m of taxonomy.models) {
      if (!m || !m.family) continue;
      const fam = String(m.family);
      const aliases = Array.isArray(m.aliases) ? m.aliases : [];
      for (const alias of aliases) {
        if (!alias) continue;
        const nk = normToken(alias);
        const ck = compactToken(alias);
        if (nk && !model.has(nk)) model.set(nk, fam);
        if (ck && !model.has(ck)) model.set(ck, fam);
      }
    }
  }
  return { hw, model };
}

function resolveHwAlias(hw, aliases) {
  if (!hw || !aliases) return null;
  const idx = aliases.hw instanceof Map ? aliases : buildAliasIndex(aliases);
  return idx.hw.get(normToken(hw)) || idx.hw.get(compactToken(hw)) || null;
}

function resolveModelAlias(model, aliases) {
  if (!model || !aliases) return null;
  const idx = aliases.model instanceof Map ? aliases : buildAliasIndex(aliases);
  return idx.model.get(normToken(model)) || idx.model.get(compactToken(model)) || null;
}

function _hwMatchesSingle(row, hw) {
  const want = normToken(hw);
  const arch = normToken(row.hw_arch);
  const vendor = normToken(row.hw_vendor);
  if (arch === want || vendor === want) return true;
  if (arch.startsWith(want) || vendor.startsWith(want)) return true;
  const name = normToken(row.hw_name);
  if (name && name.includes(want)) return true;
  return false;
}

/** "sm_86", "nvidia", "nvid", "rtx 3090" -> which hw rows are in scope. CONTRACT §4. */
function hwMatches(row, hw, aliases) {
  if (!hw) return true;
  if (_hwMatchesSingle(row, hw)) return true;
  const resolved = resolveHwAlias(hw, aliases);
  if (resolved && _hwMatchesSingle(row, resolved)) return true;
  return false;
}

function _modelMatchesSingle(row, model) {
  const want = normToken(model);
  const fam = normToken(row.model_family);
  if (fam === want) return true;
  if (want && fam && (want.includes(fam) || fam.includes(want))) return true;
  return false;
}

/**
 * CONTRACT §4: model_family exactly, else contains. `*` rows are never an answer
 * to a model question (§3); callers keep them aside as context.
 */
function modelMatchesExact(row, model, aliases) {
  if (!model) return true;
  if (row.model_family === '*') return false;
  if (_modelMatchesSingle(row, model)) return true;
  const resolved = resolveModelAlias(model, aliases);
  if (resolved && _modelMatchesSingle(row, resolved)) return true;
  return false;
}

/** Runtime: slug, then display name (`runtime_label` when the dataset carries it). */
function runtimeMatches(row, runtime) {
  if (!runtime) return true;
  const want = normToken(runtime);
  const slug = normToken(row.runtime);
  if (!slug) return false;
  if (slug === want) return true;
  const label = normToken(row.runtime_label);
  if (label && label === want) return true;
  if (label && want && label.includes(want)) return true;
  return keyify(row.runtime) === keyify(runtime);
}

/**
 * Free-text match — mirrors api/store.py `_has_text`: the needle is looked for
 * in a fixed field list plus every evidence quote and url. Kept identical so a
 * `q=` filter returns the same rows statically and from the API.
 */
function freeTextMatches(row, q) {
  if (!q) return true;
  const needle = String(q).toLowerCase();
  const hay = [
    row.id,
    row.hw_vendor,
    row.hw_arch,
    row.hw_name,
    row.model_family,
    row.model_rev,
    row.runtime,
    row.runtime_rev,
    row.quant,
    row.notes,
    row.status,
    row.source_kind
  ]
    .map((v) => (v === null || v === undefined ? '' : String(v)))
    .join(' ')
    .toLowerCase();
  if (hay.includes(needle)) return true;
  for (const ev of Array.isArray(row.evidence) ? row.evidence : []) {
    if (!ev || typeof ev !== 'object') continue;
    if (String(ev.quote || '').toLowerCase().includes(needle)) return true;
    if (String(ev.url || '').toLowerCase().includes(needle)) return true;
  }
  return false;
}

/* ----------------------------------------------------------------- lookup */

/**
 * The plain-language miss headline the UI shows above everything else.
 * Kept here (not in render.js) so it is testable and so the API and the static
 * page phrase a miss identically.
 *
 *   missSentence({hw:'sm_86', model:'qwen3', runtime:null})
 *     -> 'No claim on record for sm_86 × qwen3'
 */
function missSentence(query) {
  const parts = [query && query.hw, query && query.model, query && query.runtime]
    .map((v) => (v === null || v === undefined || v === '' ? null : String(v)))
    .filter((v) => v !== null);
  if (!parts.length) return 'No claim on record for any combination';
  return `No claim on record for ${parts.join(' × ')}`;
}

/**
 * The whole read path, as a pure function.
 *
 * @param {Array<object>} rows       normalized (or raw) rows
 * @param {object|URLSearchParams} query  {hw, model, runtime, status, kind, q, limit}
 * @param {object} [dataset]         {rows, as_of, version} for the meta block
 * @param {object} [opts]            {now: Date, datasetSource: string}
 * @returns {object} CONTRACT §4 response
 */
function lookup(rows, query, dataset, taxonomyOrOpts, maybeOpts) {
  let taxonomy = null;
  let opts = {};
  if (taxonomyOrOpts && (taxonomyOrOpts.hw_aliases || taxonomyOrOpts.models || taxonomyOrOpts.hw instanceof Map)) {
    taxonomy = taxonomyOrOpts;
    opts = maybeOpts || {};
  } else {
    opts = taxonomyOrOpts || {};
    taxonomy = opts.taxonomy || (dataset && dataset.taxonomy) || null;
  }
  const aliases = taxonomy ? buildAliasIndex(taxonomy) : null;

  const all = (rows || []).map(normalizeRow);
  const q = query instanceof URLSearchParams ? buildQuery(query) : { ...buildQuery(query) };
  const askModel = Boolean(q.model);

  // Did this query name any lookup dimension at all? A filter-only query
  // (status=untested) is a browse, not a lookup, and never produces is_miss.
  const dimensioned = Boolean(q.hw || q.model || q.runtime);

  // Exactly api/store.py `matches(include_status=False)`: hw + runtime + model +
  // kind + free text all filter which rows exist for this query; `status` does
  // NOT (it only narrows returned answer rows). `stars` are the `*` rows among
  // those matches — the hardware-level claims that the counters report.
  const onRecord = all.filter(
    (r) =>
      hwMatches(r, q.hw, aliases) &&
      runtimeMatches(r, q.runtime) &&
      (r.model_family === '*' || modelMatchesExact(r, q.model, aliases)) &&
      (!q.kind || r.source_kind === q.kind) &&
      (!q.q || freeTextMatches(r, q.q))
  );
  const stars = onRecord.filter((r) => r.model_family === '*');
  const nonStars = onRecord.filter((r) => r.model_family !== '*' && modelMatchesExact(r, q.model, aliases));

  // A query with no model asked for: hardware-level (`*`) rows are legitimate
  // ANSWERS to "does this card work at all". With a model asked for they are
  // context only and never count as an answer (§3). Mirrors api/store.py.
  let answers = askModel ? [...nonStars] : [...nonStars, ...stars];
  if (q.status) answers = answers.filter((r) => r.status === q.status);
  answers = sortRows(answers);

  // `context` carries `*` rows ONLY when a model was asked — otherwise they were
  // promoted into `rows`, and listing them twice would double-count them.
  // (api/store.py: `context_out = [] if not ask_model else stars`.)
  const context = askModel ? stars : [];
  // A query that filters at all (dimensions or free text) can be a miss; a
  // completely empty query is a browse, never a miss.
  const filtered = Boolean(q.hw || q.model || q.runtime || q.q || q.kind || q.status);
  const isMiss = filtered && answers.length === 0;

  const response = {
    query: { hw: q.hw, model: q.model, runtime: q.runtime, status: q.status, kind: q.kind, q: q.q, limit: q.limit },
    rows: answers.slice(0, q.limit),
    context: context.slice(0, q.limit),
    miss: null,
    query_id: hash8(JSON.stringify([q.hw, q.model, q.runtime, q.status, q.kind, q.q])),
    generated_at: new Date(opts.now || Date.now()).toISOString().replace(/\.\d{3}Z$/, 'Z'),
    dataset: mergeDataset(dataset, all, opts)
  };
  response.total = answers.length;

  if (isMiss) {
    response.miss = buildMiss(onRecord, stars, q);
  }
  return response;
}

/**
 * Answer ordering — same rule as api/store.py `_sort_key`: untested (with basis
 * first, then without basis, then votes desc) first, then solved, then rejected;
 * newest as_of first within a status.
 */
function sortRows(rows) {
  const rank = { untested: 0, solved: 1, rejected: 2 };
  return [...rows].sort((a, b) => {
    const ra = rank[a.status] ?? 3;
    const rb = rank[b.status] ?? 3;
    if (ra !== rb) return ra - rb;
    if (a.status === 'untested' && b.status === 'untested') {
      const ba = a.basis ? 0 : 1;
      const bb = b.basis ? 0 : 1;
      if (ba !== bb) return ba - bb;
    }
    const dv = (b.want_votes || 0) - (a.want_votes || 0);
    if (dv) return dv;
    const ad = String(a.as_of || '');
    const bd = String(b.as_of || '');
    if (ad !== bd) return ad < bd ? 1 : -1;
    return String(a.id).localeCompare(String(b.id));
  });
}

function mergeDataset(dataset, rows, opts) {
  const base = dataset && dataset.as_of !== undefined ? dataset : datasetFromRows(rows);
  const out = {
    rows: typeof base.rows === 'number' ? base.rows : rows.length,
    as_of: base.as_of || datasetFromRows(rows).as_of,
    version: base.version || null
  };
  const source = base.source || opts.datasetSource;
  if (source) out.source = source;
  if (base.generated_at) out.generated_at = base.generated_at;
  return out;
}

/**
 * The miss object — CONTRACT §4. Every key is always present.
 *
 * `onRecord` = rows matching hw + runtime + model with status/kind/q ignored,
 * `stars` = the `*` rows among them. Mirrors api/store.py `_miss` so the static
 * fallback and the live API name the same reason for the same query.
 *
 * reason precedence (first match wins):
 *   no-match         nothing matched at all, `*` rows included
 *   wanted-only      every matching claim for this combination is wanted
 *   rejected-only    every matching claim for this combination is rejected
 *   partial-context  hardware-level (`*`) claims exist, no model-specific claim
 *
 */
function buildMiss(onRecord, stars, q) {
  // Mirrors api/store.py `_miss`: `unfiltered` = non-star rows matching the
  // dimensions with the status filter ignored; `stars` = `*` rows that matched.
  const unfiltered = onRecord.filter((r) => r.model_family !== '*');
  const statuses = new Set(unfiltered.map((r) => r.status));

  let reason;
  if (unfiltered.length === 0 && stars.length === 0) {
    reason = 'no-match';
  } else if (unfiltered.length > 0 && statuses.size === 1 && statuses.has('untested')) {
    reason = 'untested-only';
  } else if (unfiltered.length > 0 && statuses.size === 1 && statuses.has('rejected')) {
    reason = 'rejected-only';
  } else if (unfiltered.length === 0 && stars.length > 0) {
    reason = 'partial-context';
  } else {
    reason = 'no-match';
  }
  if (!MISS_REASONS.includes(reason)) reason = 'no-claim';

  const untested = unfiltered.filter((r) => r.status === 'untested');
  const rejected = unfiltered.filter((r) => r.status === 'rejected');

  const partial = stars.length > 0;
  const knownUntested = untested.length > 0;
  const wantedVotes = untested.reduce((n, r) => Math.max(n, r.want_votes || 0), 0);
  const untestedBasis = [...new Set(untested.map((r) => r.basis).filter(Boolean))].sort();
  const neighbourUntested = unfiltered.filter((r) => r.status === 'untested');
  const neighbourVotes = neighbourUntested.reduce((n, r) => Math.max(n, r.want_votes || 0), 0);
  const lastChecked =
    [...(unfiltered.length ? unfiltered : stars)]
      .map((r) => r.as_of)
      .filter(isDate)
      .sort()
      .pop() || null;

  return {
    is_miss: true,
    reason,
    partial,
    hint: hintFor(reason, q, {
      stars,
      untested,
      rejected,
      knownUntested,
      wantedVotes,
      untestedBasis,
      neighbourUntested,
      neighbourVotes
    }),
    known_untested: knownUntested,
    known_wanted: knownUntested,
    wanted_votes: wantedVotes,
    untested_basis: untestedBasis,
    last_checked: lastChecked,
    counts: { exact: 0, context: stars.length }
  };
}

function label(v) {
  return v === null || v === undefined || v === '' ? null : String(v);
}

function hintFor(reason, q, ctx) {
  const hw = label(q.hw) || 'this hardware';
  const model = label(q.model) || 'this model';
  const runtime = label(q.runtime);
  const combo = `${hw}${runtime ? ` × ${runtime}` : ''}`;
  const runtimes = [...new Set(ctx.stars.map((r) => r.runtime))];
  const neighbour =
    reason === 'no-match' && ctx.neighbourUntested && ctx.neighbourUntested.length > 0
      ? ` Elsewhere for this card: ${ctx.neighbourVotes} vote${ctx.neighbourVotes === 1 ? '' : 's'} exist, but for ${ctx.neighbourUntested
          .map((r) => r.model_family)
          .join(', ')} — different models, not an answer here.`
      : '';

  switch (reason) {
    case 'partial-context': {
      // Only name the runtimes when the query didn't already pin one.
      const rtNote = !runtime && runtimes.length ? ` (${runtimes.join(', ')})` : '';
      // If other models DO have specific claims for this card, say so — that is
      // the difference between "untracked everywhere" and "untracked for you".
      const modelled = ctx.stars
        .flatMap((r) => (Array.isArray(r.covers_models) ? r.covers_models : []))
        .filter(Boolean);
      const covered = [...new Set(modelled)].slice(0, 6);
      const coveredNote = covered.length
        ? ` This card has model-specific claims for ${covered.join(', ')} — but not for ${model}.`
        : '';
      return (
        `The backend claims support for ${combo}${rtNote}, but no claim names ${model}. ` +
        `A hardware-level row says the backend builds on this card; it does not say ${model} runs on it.${coveredNote}`
      );
    }
    case 'untested-only': {
      const basisNote =
        ctx.untestedBasis && ctx.untestedBasis.length
          ? ` Basis: ${ctx.untestedBasis.join(', ')}.`
          : '';
      const voteNote = ` Demand: ${ctx.wantedVotes} vote${ctx.wantedVotes === 1 ? '' : 's'}.`;
      return (
        `Proposed, unverified: ${combo} × ${model} has no confirmed run on record.${basisNote}${voteNote} ` +
        `Treat as unverified until someone records a working pointer.`
      );
    }
    case 'rejected-only':
      return (
        `${combo} × ${model} was tried and is recorded as rejected. Read the notes before trying it yourself — ` +
        `that is the point of keeping them.`
      );
    case 'no-match':
      return `Nothing in the dataset matches ${[q.hw, q.model, q.runtime].filter(Boolean).map(String).join(' × ') || 'that query'} — not even a hardware-level claim. Check the spelling, or widen the query.`;
    case 'no-claim':
    default:
      return `No claim on record for ${combo} × ${model}.${neighbour}`;
  }
}

/* ------------------------------------------------------- detail helpers */

/** All rows for one exact combination (answers + `*` context), for a detail view. */
function rowsForCombo(rows, hwArch, modelFamily, runtime) {
  const all = (rows || []).map(normalizeRow);
  const answers = all.filter(
    (r) =>
      r.hw_arch === hwArch &&
      r.model_family === modelFamily &&
      r.model_family !== '*' &&
      runtimeMatches(r, runtime)
  );
  const context = all.filter(
    (r) => r.hw_arch === hwArch && r.model_family === '*' && runtimeMatches(r, runtime)
  );
  return { answers, context };
}

/** CONTRACT: wanted sorted by votes desc, then want_first asc. */
function sortWanted(rows) {
  return [...rows].sort((a, b) => {
    const dv = (b.want_votes || 0) - (a.want_votes || 0);
    if (dv) return dv;
    const af = a.want_first || '9999-99-99';
    const bf = b.want_first || '9999-99-99';
    return af < bf ? -1 : af > bf ? 1 : 0;
  });
}

/** Distinct values for filter UI, in stable order. */
function facets(rows) {
  const vendors = new Map();
  const models = new Map();
  const runtimes = new Map();
  const arches = new Map();
  for (const r of (rows || []).map(normalizeRow)) {
    if (r.model_family !== '*' && r.model_family) {
      const m = models.get(r.model_family) || { value: r.model_family, count: 0 };
      m.count++;
      models.set(r.model_family, m);
    }
    if (r.runtime) {
      const m = runtimes.get(r.runtime) || { value: r.runtime, count: 0 };
      m.count++;
      runtimes.set(r.runtime, m);
    }
    if (r.hw_vendor) {
      const v = vendors.get(r.hw_vendor) || { value: r.hw_vendor, label: r.hw_vendor, count: 0, arches: new Map() };
      v.count++;
      const a = v.arches.get(r.hw_arch) || { value: r.hw_arch, label: r.hw_name || r.hw_arch, count: 0 };
      a.count++;
      v.arches.set(r.hw_arch, a);
      vendors.set(r.hw_vendor, v);
    }
    if (r.hw_arch) {
      const a = arches.get(r.hw_arch) || { value: r.hw_arch, vendor: r.hw_vendor, label: r.hw_name || r.hw_arch, count: 0 };
      a.count++;
      arches.set(r.hw_arch, a);
    }
  }
  const byCountThenName = (a, b) => b.count - a.count || a.value.localeCompare(b.value);
  return {
    vendors: [...vendors.values()]
      .map((v) => ({ ...v, arches: [...v.arches.values()].sort(byCountThenName) }))
      .sort((a, b) => a.value.localeCompare(b.value)),
    arches: [...arches.values()].sort(byCountThenName),
    models: [...models.values()].sort(byCountThenName),
    runtimes: [...runtimes.values()].sort(byCountThenName)
  };
}

/**
 * Partition a flat list of rows into parent groups and orphan variants.
 * Variants with `row.parent` are attached under their parent row (and tagged
 * `parent_untested: true` if parent has `status === 'untested'`).
 */
function groupVariants(rows) {
  const list = rows || [];
  const byId = new Map();
  const parents = [];
  const orphans = [];

  for (const r of list) {
    if (!r.parent) {
      const entry = { row: r, variants: [] };
      byId.set(r.id, entry);
      parents.push(entry);
    }
  }
  for (const r of list) {
    if (r.parent) {
      const p = byId.get(r.parent);
      if (p) {
        const v = p.row.status === 'untested' ? { ...r, parent_untested: true } : r;
        p.variants.push(v);
      } else {
        orphans.push(r);
      }
    }
  }
  return { parents, orphans };
}

  Object.assign(SR, { MISS_REASONS, STATUSES, SOURCE_KINDS, keyify, hash8, normalizeData, normalizeRow, datasetFromRows, buildQuery, normToken, compactToken, buildAliasIndex, resolveHwAlias, resolveModelAlias, hwMatches, modelMatchesExact, runtimeMatches, freeTextMatches, missSentence, missHint: hintFor, lookup, sortRows, groupVariants, rowsForCombo, sortWanted, facets });
})(window.__SR = window.__SR || {});
