import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webDir = path.resolve(__dirname, '..');

function loadWebScripts() {
  const errors = [];
  const sandbox = {
    window: null,
    console: {
      log: () => {},
      info: () => {},
      warn: (...args) => errors.push(`console.warn: ${args.join(' ')}`),
      error: (...args) => errors.push(`console.error: ${args.join(' ')}`),
    },
    setTimeout,
    clearTimeout,
    URLSearchParams,
    encodeURIComponent,
    decodeURIComponent,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;

  const ctx = vm.createContext(sandbox);
  for (const rel of ['snapshot.js', 'js/lookup.js', 'js/format.js', 'js/render.js']) {
    const code = fs.readFileSync(path.join(webDir, rel), 'utf8');
    vm.runInContext(code, ctx, { filename: rel });
  }
  return { ctx, errors };
}

test('index.html references snapshot.js and core scripts', () => {
  const html = fs.readFileSync(path.join(webDir, 'index.html'), 'utf8');
  for (const script of ['snapshot.js', 'js/lookup.js', 'js/format.js', 'js/render.js', 'js/api.js', 'js/app.js']) {
    assert.ok(html.includes(`src="${script}"`), `index.html should reference ${script}`);
  }
});

test('snapshot.js loads with zero errors and renders expected combo rows on lookup/filter', () => {
  const { ctx, errors } = loadWebScripts();
  assert.deepEqual(errors, [], `Expected zero console errors/warnings, got: ${errors.join('; ')}`);

  assert.ok(ctx.SOLVE_RUN_SNAPSHOT, 'SOLVE_RUN_SNAPSHOT should be defined');
  assert.ok(Array.isArray(ctx.SOLVE_RUN_SNAPSHOT.rows), 'snapshot rows should be an array');
  assert.ok(ctx.SOLVE_RUN_SNAPSHOT.rows.length > 0, 'snapshot should contain at least 1 row');

  const SR = ctx.__SR;
  assert.ok(SR, 'window.__SR should be initialized');

  const dataset = SR.normalizeData(ctx.SOLVE_RUN_SNAPSHOT);
  assert.ok(dataset.rows.length > 0, 'normalized dataset should contain rows');

  // Search/filter for a known combo in snapshot.js: amd/gfx1100/qwen3/llama_cpp
  const result = SR.lookup(dataset.rows, { hw: 'gfx1100', model: 'qwen3', runtime: 'llama.cpp' });
  assert.ok(result.rows.length >= 1, 'lookup(gfx1100, qwen3, llama.cpp) should return >= 1 row');
  assert.equal(result.rows[0].hw_arch, 'gfx1100');
  assert.equal(result.rows[0].model_family, 'qwen3');

  // Verify rendering produces expected combo HTML
  const cardHtml = SR.cardFor(result.rows[0]);
  assert.ok(cardHtml.includes('gfx1100'), 'rendered card should include hw_arch');
  assert.ok(cardHtml.includes('qwen3'), 'rendered card should include model_family');

  const tableHtml = SR.browseTable(result.rows, dataset.rows.length, { key: 'updated', dir: 'desc' });
  assert.ok(tableHtml.includes('<table class="rows">'), 'browseTable should render rows table');
  assert.ok(tableHtml.includes('gfx1100'), 'browseTable should include filtered combo row');

  // Empty filter result renders empty state cleanly
  const emptyTableHtml = SR.browseTable([], dataset.rows.length, { key: 'updated', dir: 'desc' });
  assert.ok(emptyTableHtml.includes('No rows match these filters.'), 'empty browseTable should render empty state');
});

test('SOLVE_RUN_SNAPSHOT.taxonomy includes hw_aliases and models', () => {
  const { ctx } = loadWebScripts();
  const tax = ctx.SOLVE_RUN_SNAPSHOT.taxonomy;
  assert.ok(tax && typeof tax === 'object', 'taxonomy should be present');
  assert.ok(tax.hw_aliases && Object.keys(tax.hw_aliases).length > 0, 'hw_aliases should be non-empty');
  assert.ok(tax.models && Object.keys(tax.models).length > 0, 'models should be non-empty');
});

test('JS lookup() resolves hw and model aliases', () => {
  const { ctx } = loadWebScripts();
  const SR = ctx.__SR;
  const dataset = SR.normalizeData(ctx.SOLVE_RUN_SNAPSHOT);

  const tax = ctx.SOLVE_RUN_SNAPSHOT.taxonomy;

  for (const hwQuery of ['rtx4090', 'rtx 4090']) {
    const res = SR.lookup(dataset.rows, { hw: hwQuery }, dataset, tax);
    assert.ok(res.rows.length > 0, `lookup(${hwQuery}) should return rows`);
    assert.ok(res.rows.every((r) => r.hw_arch === 'sm_89'), `lookup(${hwQuery}) should match sm_89`);
  }

  const rdna = SR.lookup(dataset.rows, { hw: 'rdna3' }, dataset, tax);
  assert.ok(rdna.rows.length > 0, 'lookup(rdna3) should return rows');
  assert.ok(rdna.rows.every((r) => r.hw_arch === 'gfx1100'), 'lookup(rdna3) should match gfx1100');

  const llama = SR.lookup(dataset.rows, { model: 'llama3' }, dataset, tax);
  assert.ok(llama.rows.length > 0, 'lookup(llama3) should return rows');
  assert.ok(llama.rows.every((r) => r.model_family === 'llama-3'), 'lookup(llama3) should match llama-3');

  const qwen = SR.lookup(dataset.rows, { model: 'qwen-3' }, dataset, tax);
  assert.ok(qwen.rows.length > 0, 'lookup(qwen-3) should return rows');
  assert.ok(qwen.rows.some((r) => r.model_family === 'qwen3'), 'lookup(qwen-3) should match qwen3');
});

test('idFor() in app.js produces 4-segment canonical IDs with dots replaced by underscores', () => {
  const appSrc = fs.readFileSync(path.join(webDir, 'js/app.js'), 'utf8');
  assert.ok(appSrc.includes('function idFor('), 'app.js should define idFor()');
  assert.ok(appSrc.includes(".replace(/\\./g, '_')"), 'idFor() should replace dots with underscores');
});

test('cardFor() and cardGroup() render hw_extra, untested basis vs want_votes, and double-wish variant warning', () => {
  const { ctx } = loadWebScripts();
  const SR = ctx.__SR;

  const extraRow = {
    id: 'nvidia/sm_89/llama-3/llama_cpp',
    status: 'solved',
    hw_vendor: 'nvidia',
    hw_arch: 'sm_89',
    hw_extra: { vram_gb: 24, cuda: '12.4' },
    model_family: 'llama-3',
    runtime: 'llama.cpp',
    evidence: [{ url: 'https://example.com/ptr', kind: 'upstream-doc' }],
    updated: '2026-11-23',
  };
  const extraHtml = SR.cardFor(extraRow);
  assert.ok(extraHtml.includes('24'), 'cardFor should render hw_extra vram_gb');
  assert.ok(extraHtml.includes('12.4'), 'cardFor should render hw_extra cuda');

  const untestedParent = {
    id: 'amd/gfx1100/llama-3/vllm',
    status: 'untested',
    hw_vendor: 'amd',
    hw_arch: 'gfx1100',
    model_family: 'llama-3',
    runtime: 'vllm',
    basis: 'rocm-6.2',
    want_votes: 5,
    updated: '2026-11-23',
  };
  const untestedVariant = {
    id: 'amd/gfx1100/llama-3/vllm/@q4_k_m',
    parent: 'amd/gfx1100/llama-3/vllm',
    status: 'untested',
    hw_vendor: 'amd',
    hw_arch: 'gfx1100',
    model_family: 'llama-3',
    runtime: 'vllm',
    quant: 'q4_k_m',
    want_votes: 2,
    updated: '2026-11-23',
  };
  const grouped = SR.groupVariants([untestedParent, untestedVariant]);
  const untestedHtml = SR.cardGroup({ parent: grouped.parents[0].row, variants: grouped.parents[0].variants });
  assert.ok(untestedHtml.toLowerCase().includes('proposed, unverified'), 'untested card should render Proposed, unverified');
  assert.ok(untestedHtml.includes('rocm-6.2'), 'untested card should render basis');
  assert.ok(untestedHtml.includes('5'), 'untested card should render want_votes');
  assert.ok(untestedHtml.includes('q4_k_m'), 'untested cardGroup should render nested variant');
  assert.ok(untestedHtml.includes('double-wish'), 'untested cardGroup should render double-wish warning');
});

test('missPanel() contains 1-click submit pointer GitHub issue link', () => {
  const { ctx } = loadWebScripts();
  const SR = ctx.__SR;
  const html = SR.missPanel(
    { is_miss: true, reason: 'no-match', query: { hw: 'rtx4090', model: 'llama3', runtime: 'llama.cpp' } },
    { payload: { hw: 'rtx4090', model: 'llama3', runtime: 'llama.cpp' } },
  );
  assert.ok(html.includes('I got this working'), 'missPanel should contain 1-click submit pointer text');
  assert.ok(html.includes('github.com'), 'missPanel should contain GitHub issue link');
});

test('groupVariants() nests variant rows under their parent card and Untested (0) renders cleanly', () => {
  const { ctx } = loadWebScripts();
  const SR = ctx.__SR;
  const parent = { id: 'nvidia/sm_89/qwen3/llama_cpp', status: 'solved', hw_vendor: 'nvidia', hw_arch: 'sm_89', model_family: 'qwen3', runtime: 'llama.cpp' };
  const variant = { id: 'nvidia/sm_89/qwen3/llama_cpp/@q4_k_m', parent: 'nvidia/sm_89/qwen3/llama_cpp', status: 'solved', hw_vendor: 'nvidia', hw_arch: 'sm_89', model_family: 'qwen3', runtime: 'llama.cpp', quant: 'q4_k_m' };
  const grouped = SR.groupVariants([parent, variant]);
  assert.equal(grouped.parents.length, 1, 'groupVariants should collapse variant under parent');
  assert.equal(grouped.parents[0].variants.length, 1, 'parent should have 1 nested variant');

  if (typeof SR.untestedTable === 'function') {
    const emptyUntested = SR.untestedTable([]);
    assert.ok(emptyUntested.includes('0') || emptyUntested.toLowerCase().includes('no '), 'Untested (0) empty state should render cleanly');
  }
});
