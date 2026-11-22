# Post-Release & Growth Plan (`solve.run`)

> **Context:** `ee63ee4` landed the v1.0 release fixups. This plan covers the next wave: **CI/CD, repo hygiene, community contribution loops, and frontend verification**—the things that turn a clean repo into a living, credible public project.

---

## Wave 1 — Parallel Agents (Disjoint Write Scopes)

### Agent B1: CI/CD & Repo Hygiene
- **Scope:** `.github/workflows/ci.yml`, `.gitignore`, `api/AGENT.md`
- **Tasks:**
  1. Add `.github/workflows/ci.yml` running on `push` and `pull_request` to `main`:
     - `python3 pipeline/tests/test_pipeline.py`
     - `python3 api/tests/test_api.py`
     - `python3 pipeline/build.py --check`
  2. Update `.gitignore` to exclude local pipeline state/cache files (`pipeline/.build-report.json`, `pipeline/.build-state.json`, `pipeline/.linkcache.json`).
  3. Remove or archive `api/AGENT.md` if it contains internal agent-only instructions not meant for public contributors.

### Agent B2: Community Evidence & Deep-Link UX
- **Scope:** `web/js/render.js`, `web/js/app.js` (read-only on `CONTRACT.md`)
- **Tasks:**
  1. Add a 1-click **"Submit evidence / report issue"** link on combo cards that opens a pre-filled GitHub issue URL with `combo_id`, `hardware`, `model`, `runtime`, and current `state`.
  2. Verify every lookup/filter state updates the URL query/hash cleanly so users can share direct links to any combo on `r/LocalLLaMA`, Discord, or GitHub.

### Agent B3: Frontend Smoke Test
- **Scope:** `web/tests/` (new directory)
- **Tasks:**
  1. Add a lightweight automated smoke test (e.g., Node/Playwright or headless check) that loads `web/index.html` with `web/snapshot.js`, verifies zero console/page errors, and checks that searching/filtering renders expected combo rows.
  2. Wire it into `.github/workflows/ci.yml` (coordinate with B1 or add as a separate job).

---

## Wave 2 — Deploy & Launch
1. **Deploy** to VPS using `api/DEPLOY.md` + `api/Caddyfile` and verify `/api/health` and live writes (`/api/want`, `/api/miss`).
2. **Launch post** on `r/LocalLLaMA` / Hacker News / X: frame it around the *problem* (fragmented local inference compatibility) and invite people to log their `miss`es or submit verified `solved` combos.
