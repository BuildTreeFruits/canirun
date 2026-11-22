/* format.js — classic script build (see web/tools/to-classic.mjs).
   Loaded in order from index.html so the site also works from file://,
   where browsers block ES modules and fetch(). Source of truth is this file. */
(function (SR) {
'use strict';
/**
 * format.js — small pure formatters. No DOM.
 * Dates are handled as plain YYYY-MM-DD strings (CONTRACT §1) so nothing shifts
 * by timezone: a row's as_of is a *day*, and rendering it as a local midnight
 * would let it drift across a date line.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-11-22" -> "22 Nov 2026". Returns the input unchanged if unparseable. */
function formatDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  if (!m) return iso || '—';
  const [, y, mo, d] = m;
  return `${Number(d)} ${MONTHS[Number(mo) - 1] || mo} ${y}`;
}

/** "2026-11-22" -> "2026-11-22" (short, for dense tables). */
function formatDateShort(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  return m ? `${m[1]}-${m[2]}-${m[3]}` : iso || '—';
}

/** Whole days between two YYYY-MM-DD dates (b - a). Calendar days, UTC-noon based. */
function daysBetween(a, b) {
  const pa = parseDay(a);
  const pb = parseDay(b);
  if (!pa || !pb) return null;
  return Math.round((pb - pa) / 86400000);
}

function parseDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  if (!m) return null;
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12);
}

/**
 * Human age of a date relative to `now`: "3 days ago", "2 years ago", "today".
 * Returns {text, days, bucket} where bucket is fresh | aging | stale.
 *
 * Thresholds are the decay rule from the notes: a two-year-old wanted row must
 * not look like a two-day-old one. 14 days is where a wanted row starts to look
 * neglected; 180 where it is a standing gap.
 */
function ageOf(iso, now = new Date()) {
  const today = toDayString(now);
  const days = daysBetween(iso, today);
  if (days === null) return { text: 'date unknown', days: null, bucket: 'fresh' };
  if (days < 0) return { text: 'in the future', days, bucket: 'fresh' };
  const bucket = days >= 180 ? 'stale' : days >= 14 ? 'aging' : 'fresh';
  return { text: relative(days), days, bucket };
}

function relative(days) {
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 14) return `${days} days ago`;
  if (days < 60) {
    const w = Math.round(days / 7);
    return `${w} week${w === 1 ? '' : 's'} ago`;
  }
  if (days < 365) {
    const mo = Math.round(days / 30);
    return `${mo} month${mo === 1 ? '' : 's'} ago`;
  }
  const y = Math.floor(days / 365);
  const remMo = Math.round((days - y * 365) / 30);
  const years = `${y} year${y === 1 ? '' : 's'}`;
  if (y === 1 && remMo >= 1) return `${years} ${remMo} month${remMo === 1 ? '' : 's'} ago`;
  return `${years} ago`;
}

/** 0..3 bars: how stale a wanted row is, for the tiny age meter. */
function ageLevel(days) {
  if (days === null || days === undefined) return 0;
  if (days >= 365) return 3;
  if (days >= 60) return 2;
  if (days >= 14) return 1;
  return 0;
}

function toDayString(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/**
 * The domain of a URL, shown *before* the link (CONTRACT failure mode 5: a miss
 * list is a "what to build" list and anyone can point a row at malicious code —
 * so the user reads the host before deciding to click).
 */
function domainOf(url) {
  try {
    const u = new URL(String(url || ''));
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return u.protocol.replace(':', '') || 'unknown';
    return u.hostname.replace(/^www\./, '');
  } catch {
    return 'unknown host';
  }
}

/** Path + query of a URL, for the greyed-out detail line under the domain. */
function pathOf(url) {
  try {
    const u = new URL(String(url || ''));
    const p = u.pathname === '/' ? '/' : u.pathname;
    return `${p}${u.search || ''}${u.hash || ''}`;
  } catch {
    return String(url || '');
  }
}

function isSafeHttp(url) {
  try {
    const u = new URL(String(url || ''));
    return u.protocol === 'https:' || u.protocol === 'http:';
  } catch {
    return false;
  }
}

/** "sm_86" -> "sm 86" for prose; ids keep the raw form. */
function humanizeSlug(s) {
  return String(s || '').replace(/[-_]/g, ' ');
}

function plural(n, one, many) {
  return n === 1 ? one : many || `${one}s`;
}

/** Pretty-print JSON compactly enough to paste; stable key order via reviver-free copy. */
function prettyJson(obj) {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

function titleCase(s) {
  return String(s || '').replace(/(^|[\s-])(\w)/g, (m, sp, c) => sp + c.toUpperCase());
}

  Object.assign(SR, { formatDate, formatDateShort, daysBetween, ageOf, ageLevel, toDayString, domainOf, pathOf, isSafeHttp, humanizeSlug, plural, prettyJson, titleCase });
})(window.__SR = window.__SR || {});
