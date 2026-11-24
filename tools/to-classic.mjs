#!/usr/bin/env node
/**
 * Converts js/*.js from ES modules to classic scripts that share a namespace.
 *
 * Why: the brief requires the site to open by double-clicking index.html. On
 * file:// browsers block ES module loading (CORS, origin "null") AND fetch(), so
 * the only way one codebase can run in both modes is classic <script> tags.
 *
 * Each file becomes an IIFE that reads its dependencies from `window.__SR` and
 * writes its public surface back. Source stays one copy — this script is the
 * migration, not a build step the user runs.
 *
 *   node web/tools/to-classic.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const js = join(here, '..', 'js');
const ORDER = ['lookup.js', 'format.js', 'render.js', 'api.js', 'app.js'];

for (const file of ORDER) {
  let src = readFileSync(join(js, file), 'utf8');
  const imported = [];

  // strip `import ... from './x.js';` -> record names
  src = src.replace(/^import\s+\{([^}]+)\}\s+from\s+['"]\.\/([\w.]+)['"];\n/gm, (m, names, mod) => {
    for (const n of names.split(',').map((s) => s.trim()).filter(Boolean)) {
      imported.push([n, mod]);
    }
    return '';
  });
  // `import * as R from './render.js';` -> const R = { ...namespace subset }
  src = src.replace(/^import\s+\*\s+as\s+([\w$]+)\s+from\s+['"]\.\/([\w.]+)['"];\n/gm, (m, name) => {
    return `  // namespace import: ${name} is bound below from SR\n`;
  });
  // bare `import './x.js';`
  src = src.replace(/^import\s+['"]\.\/([\w.]+)['"];\n/gm, '');

  // collect exports
  const exported = [];
  src = src.replace(/^export\s+(const|let|function|async function|class)\s+([A-Za-z_$][\w$]*)/gm, (m, kw, name) => {
    exported.push(name);
    return `${kw} ${name}`;
  });
  // `export { a, b };`
  src = src.replace(/^export\s*\{([^}]+)\};?\n/gm, (m, names) => {
    for (const n of names.split(',').map((s) => s.trim()).filter(Boolean)) {
      exported.push(n.split(/\s+as\s+/).pop().trim());
    }
    return '';
  });

  const header = `/* ${file} — classic script build (see web/tools/to-classic.mjs).
   Loaded in order from index.html so the site also works from file://,
   where browsers block ES modules and fetch(). Source of truth is this file. */
(function (SR) {
'use strict';
`;
  const imports = imported.length
    ? `  // dependencies pulled from the shared namespace\n  const { ${[...new Set(imported.map((i) => i[0]))].join(', ')} } = SR;\n\n`
    : '';
  const footer = `
  Object.assign(SR, { ${[...new Set(exported)].join(', ')} });
})(window.__SR = window.__SR || {});
`;
  writeFileSync(join(js, file), header + imports + src + footer);
  console.log(`${file}: ${imported.length} imports, ${exported.length} exports`);
}
