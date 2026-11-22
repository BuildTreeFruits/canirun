#!/usr/bin/env node
/**
 * Regenerates web/snapshot.js — the data the site uses on file:// (where fetch
 * and ES modules are blocked by the browser's CORS rules).
 *
 * Not part of any build the user must run: the site works over http without it.
 * It only exists so double-clicking index.html shows real content instead of an
 * empty shell. Run after the pipeline rebuilds data/combos.json:
 *
 *   node web/tools/inline-snapshot.mjs
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const combosPath = join(root, 'data', 'combos.json');

if (!existsSync(combosPath)) {
  console.error('no data/combos.json — run the pipeline first');
  process.exit(1);
}

const combos = JSON.parse(readFileSync(combosPath, 'utf8'));
const rows = Array.isArray(combos.rows) ? combos.rows : [];
const payload = {
  dataset: {
    rows: rows.length,
    as_of: combos.as_of || null,
    version: combos.version || null,
    source: 'snapshot',
    source_url: 'web/snapshot.js'
  },
  generated_at: combos.generated_at || null,
  rows
};

const out = `/**
 * snapshot.js — GENERATED. Do not edit; run \`node web/tools/inline-snapshot.mjs\`.
 *
 * A plain (non-module) script so it loads on file://, where ES modules and
 * fetch are both blocked. It carries the last-built dataset so that
 * double-clicking index.html shows real content. Served over http the app
 * prefers /api/lookup and ignores this file.
 *
 * built: ${new Date().toISOString()} · rows: ${rows.length} · as_of: ${payload.dataset.as_of}
 */
window.SOLVE_RUN_SNAPSHOT = ${JSON.stringify(payload)};
`;

writeFileSync(join(here, '..', 'snapshot.js'), out);
console.log(`wrote web/snapshot.js (${rows.length} rows, as_of ${payload.dataset.as_of})`);
