## Summary

Briefly describe the combination(s), hardware architecture/aliases, scraper update, or fix in this PR.

## Checklist

- [ ] Every added or updated combination row includes a real upstream `pointer` URL and a **verbatim** `evidence[].quote` from that URL.
- [ ] `status` follows [CONTRACT.md](../CONTRACT.md) (`solved` has a `pointer`; `untested` has a `basis`; `rejected` has `notes` explaining why it fails).
- [ ] Dataset builds and validates cleanly:
  ```bash
  python3 pipeline/build.py --check
  ```
- [ ] If `data/combos.json` or `data/taxonomy.json` changed, the offline snapshot is updated:
  ```bash
  node web/tools/inline-snapshot.mjs
  ```
- [ ] Tests pass:
  ```bash
  python3 pipeline/tests/test_pipeline.py
  python3 api/tests/test_api.py
  node --test web/tests/smoke.mjs
  ```
