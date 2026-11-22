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
