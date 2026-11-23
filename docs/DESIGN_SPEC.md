# DESIGN SPEC — variants, `untested`, and the discussion model

Status: **decided, not built.** Written 2026-11-22 16:07 EST from a design session.
Supersedes the open structure questions in the vault note
`00 My Notes/Kernel index — hardware × model × engine.md` §"Open structure questions".

Scope note: this spec covers **only** what was decided in session. The idea/program framing
(canonical pointer, negative space, no bounty) is settled and is not reopened here.

---

## 0. One-paragraph summary

The index gains **variants** — rows that are more specific than a row, hanging off a
base `hardware × model × runtime` triple via a `parent` field in the **same** rows file.
The four-state model collapses from four to **three stored states** plus the implicit
`not-searched`: `wanted` is **merged into `untested`**, which becomes the "someone
believes this works, nobody has verified it" state and carries both a `basis` (why they
believe it) and `want_votes` (how many want it). `untested` propagates to variants
rather than defaulting them to unsearched. Prose discussion is a **comment** — flat,
cheap, evidence-free — and acts as the intake channel from which a comment can be
promoted into a variant. Divergence is retired as a word; the concept is a variant.
A forum is deferred until traction, but the comment table is built so a forum is a
rendering change, not a migration.

---

## 1. Decisions (authoritative)

### D1 — Variants are the unit of specificity

A **variant** is a row that is more specific than another row. It is not an annotation,
not a caveat sidecar, and not a comment. It is the same triple with more knobs set.

Canonical id:

```
{parent id}/@{variant slug}
e.g. nvidia/sm_86/qwen3/llama_cpp/@q4km-ngl99-c8192
```

The variant slug is **derived from the distinguishing knobs**, not free text. Two
contributors filing the same configuration must produce the same slug.

Rationale: a variant is queryable, citable, linkable, and deduplicable in a way a comment
can never be. "One method works better for writing, another for coding" becomes two
variants with different `fits`, both answerable by the same lookup endpoint.

### D2 — Variants live in the same `data/rows/*.jsonl`, distinguished by `parent`

Not a separate file. `parent: null` means base combo; `parent: "<parent id>"` means variant.

Consequences, all favourable:
- `pipeline/schema.py`, `pipeline/build.py`, `pipeline/export.py` work unchanged.
- The static fallback (`web/index.html` reading `data/combos.json` with no server) keeps
  working. A separate file would have broken it or forced a second fetch.
- `api/store.py` joins nothing; the row is the row.

Cost: a variant row is a full row and pays full validation. Accepted.

### D3 — The knob set is finite and nullable

The knobs that may distinguish a variant. If a difference is not expressible here, it is a
**comment**, not a variant.

| field | example | notes |
|---|---|---|
| `quant` | `Q4_K_M` | GGUF quant or equivalent |
| `context_length` | `8192` | int |
| `offload` | `ngl=99` | layer offload / split, free string with a convention |
| `runtime_version` | `b4700` | or reuse existing `runtime_rev` |
| `driver_version` | `cuda-12.4` | CUDA / ROCm / Metal |
| `flags` | `--flash-attn` | free string |
| `fits` | `coding` | **fixed enum**, see D4 |

All nullable. A variant must set **at least one** knob, else it is a duplicate of its
parent.

### D4 — `fits` is a fixed enum, not free text

```
writing | coding | tools | long-context | multimodal | speed
```

Free text does not dedupe, and `fits` is the field most likely to be queried ("I'm coding,
what works"). A fit that does not appear here is a signal the list is incomplete — raise a
comment, do not invent a value.

### D5 — `wanted` is merged into `untested`

`wanted` is **removed** as a state. `untested` replaces it and carries both fields:

- `basis` — **required**, one of `docs-claim | analogy | author-says | mine`
- `basis_note` — free text, optional but strongly encouraged
- `want_votes` — retained; demand, not belief
- `want_first`, `want_requesters` — retained unchanged

The half of this that matters: **`want_votes` and `basis` answer different questions and
must not be conflated.** `want_votes` = how many people want this. `basis` = why the
filer thinks it works. A row can be `untested` with 12 votes and no one believing it; the
tally alone would hide that. Both are surfaced separately in the API payload (D8).

### D6 — `untested` is stored; `not-searched` remains unstored

Three stored states + the implicit one:

| state | stored | meaning |
|---|---|---|
| `solved` | yes | working path + pointer + `as_of` |
| `untested` | yes | someone believes it works, nobody verified. Requires `basis` |
| `rejected` | yes | tested, does not work. Requires `notes` |
| `not-searched` | **no** | absence of a row *is* the state |

`untested` is **not** a sibling of `not-searched` — it is the successor of `wanted`.
It is a claim; absence is silence.

### D7 — `untested` propagates to variants

A variant of an `untested` parent **inherits `untested`** and says so. It does not default
to `not-searched`. An untested variant under an untested parent is a double-wish and the
UI/API must render it as such — it must not read as a lead.

### D8 — The agent payload never presents a wish as a fact

`api/store.py::_hint()` and the row payload must state "proposed, unverified" for
`untested` rows. This is the highest-severity item in this spec: it is the one failure
that **actively misleads** a user or agent, and it is the direct analogue of the existing
`source_kind: derived` warning in the README.

### D9 — Comments are the intake channel, not a forum

A **comment** is an utterance, not a claim. It cannot be wrong.

- Flat. No nesting. No threading. No replies.
- Cheap: no evidence required, no account required at launch.
- Anchored to a row id (base combo or variant).
- Votes on comments.
- Cap: when a comment exceeds ~500 words, the discussion belongs at a `discussion_url`
  and the row points there.

**Promotion path (the whole point):** a moderator (or an agent) may **promote a comment
into a variant**, filling the knobs from the prose. Build this before the forum. Expected
split — roughly 20% of contributors fill out structured fields, 80% write a paragraph.
Designing for the 80% is what keeps the schema from staying empty while comments fill up.

### D10 — The form must not say "add a variant"

No contributor arrives thinking in our vocabulary. The contribution UI offers three
buttons:

1. **"This combination didn't work as described"** → `rejected` (or a variant with
   `rejected`) — axis auto-filled from the row clicked.
2. **"It works, with caveats"** → variant, knobs from the form.
3. **"Something else got it working"** → the most valuable path: a `solved` variant, or a
   base `solved` row that nobody had.

The friction gradient *is* the triage. Nobody decides "comment or variant" — the form asks
for evidence and the answer routes itself.

### D11 — Build the comment store for the forum that might come later

So that a forum is a rendering change and not a data migration:

- `parent_id` — nullable now (enables threading later)
- `author` — anonymous key now, handle later
- `thread_url` — nullable (enables pointing out to GitHub Discussions)

Failure mode avoided: comments as strings-on-a-row, then 4,000 of them to migrate.

### D12 — Reddit is rejected as a venue

Not on taste — structurally. Reddit is topic-threaded; this index needs row-anchored
discussion. On Reddit the discussion of `sm_86 × qwen3 × llama.cpp` lives inside a comment
tree under a post whose title is not the combination, so it can never be returned by a
lookup. A row page reachable from a search (`solve.run/nvidia/sm_86/qwen3/llama_cpp`) is
already a better venue, and Reddit cannot be that.

### D13 — No accounts; anonymous writes with an optional handle

Votes: anonymous, device-stable key — **already implemented** as
`api/server.py::_searcher_key()` and the anonymous fallback in `POST /api/want/{id}`.
Comments: same key, no account. A handle is an optional upgrade, not a requirement.

Moderation at launch scale is the maintainer's queue. That is acceptable for v1 and should
be stated in the docs rather than papered over.

### D14 — Discussion may be *pointed out to*, not hosted

Long-form writeups point to an existing GitHub Discussion or issue thread via
`discussion_url`. Existing `pointer` already does this for solutions; this extends it to
discussion. Forum depth without forum gravity.

### D15 — The site is agent-forward, not agent-only

**Correction to an assumption made mid-session.** The site has two readers:

- **Agent** — wants a short, structured, verified caveat inside the lookup JSON.
- **Human** — browses, reads three paragraphs, follows a link, decides.

Both read the same row. What differs is rendering. The row must therefore be a **page a
person would land on from a search**, not just an API response. The pure-agent framing was
over-rotated; the data model tolerates prose, and humans commenting is exactly what the
comment field needs to exist for.

Consequence for `not-searched`: for an agent it is a fact; for a human it is a question.
That URL must tell the human *what to do* — "nobody has checked this, here are the three
places to check, log it when you're done." That is the cheapest contribution funnel and it
sits behind no sign-in.

### D16 — Licences: no change. MIT stands.

Checked this session: `LICENSE` is MIT, repo is public at
`https://github.com/BuildTreeFruits/solve-run`, CI exists. The open-source ask
("someone can land a fix while I'm moving") is **already satisfied** by MIT + public repo
+ CI. No per-path licence scheme, no AGPL, no data licence was adopted. Relicensing is a
later fight that requires traction worth protecting first; optimising for protection at
zero traction is not worth build budget.

### D17 — Merge path over licence

The "can people fix this while I'm away" requirement is answered by process, not law:

- public repo ✅ (exists)
- CI validating PRs against `--check` ✅ (exists — `.github/workflows/ci.yml` runs
  `pipeline/tests`, `api/tests`, `pipeline/build.py --check`, frontend smoke on every PR)
- **a second maintainer** ❌ (missing) — invite a regular contributor when one appears.

---

## 2. Concrete change list

Line references are to the tree as of 2026-11-22 and will drift.

### 2.1 `pipeline/schema.py`

- `STATUSES` (line 33): `("solved", "wanted", "rejected")` → `("solved", "untested", "rejected")`
- Invariant 1 (line 682): keep — `not-searched` remains unstored.
- Invariant 4 (lines 797–802): rewrite. `wanted` → `untested`. New requirements:
  - `untested` requires `basis ∈ {docs-claim, analogy, author-says, mine}`
  - `untested` **does** still want `want_votes >= 1`? **No** — decide: an `untested` row
    with zero votes is legitimate (the filer believes it, nobody else cares yet).
    Recommendation: `want_votes >= 0`; `want_first` required only if `want_votes >= 1`.
- Existing vote-flip inference (lines 592–602, "rejected because we found nothing" flips to
  `wanted`) → flips to `untested` with `basis: "mine"`? **No** — an absence-claim rejection
  has no belief attached. Flip to `untested` with `basis: "docs-claim"` only if the row
  carries a pointer; otherwise leave `rejected`. Flagging this as the one sub-decision
  needing review.
- Add optional variant fields: `parent`, `quant`, `context_length`, `offload`,
  `runtime_version`, `driver_version`, `flags`, `fits`.
- New invariant: a variant (`parent` non-null) must set at least one knob.
- New invariant: `parent` must resolve to an existing row id (post-join check in `build.py`).
- New invariant: `fits` ∈ enum, or null.

### 2.2 `api/store.py`

- `_hint()` (line 533): add an `untested-only` branch returning explicit "proposed,
  unverified" language, and split `want_votes` from `basis` in the returned payload.
- `_sort_key()` (line 562): `status_rank` map `{"wanted":0,"solved":1,"rejected":2}` →
  `{"untested":0,"solved":1,"rejected":2}`. Consider ranking `untested` with a basis
  above `untested` without one.
- Row payload: expose `basis`, `basis_note`, and (for variants) knob fields + `parent`.
- Vote overlay (lines 725+): `status=="wanted"` checks → `status=="untested"`.

### 2.3 `pipeline/export.py`, `data/combos.json`

- Variants included in `combos.json` keyed by their full variant id, with `parent` field.
  Verify the static fallback in `web/index.html` groups them under the parent rather than
  listing thirty flat siblings.

### 2.4 `docs/` and `CONTRIBUTING.md`

- `CONTRIBUTING.md`: add a response-time line (reviews may take a week or more; validated
  PRs from regulars may be merged directly). Add the `untested` + `basis` fields to the
  Option B field list. Add variant contribution instructions.
- `.github/ISSUE_TEMPLATE/`: add a row-submission template (missing today — the issue path
  asks for structure in prose, so issues arrive unparseable).
- `CONTRACT.md` §1: state list update; §7 file ownership unchanged (same file per D2).

### 2.5 Nothing in this spec requires a schema migration of the *votes* store

`data/votes.json` keys are row ids. Variant ids are longer strings following the same
rules. **No vote-store change required.**

---

## 3. Not decided / open

Recorded so they don't get silently re-litigated or silently forgotten.

1. **Do confirms on a variant roll up to the parent?** Not decided. Recommendation: no.
   A confirmed variant is information *about* the parent but must not silently promote
   the parent's status; the parent's row should link to its confirmed variants instead.
2. **Does a confirmed `untested` variant with 8 confirmations flip anything?** Leaning no.
   A separate `confirms` tally was proposed; authority is unresolved. This is the item
   most likely to make the wanted/untested list read as noise if rushed.
3. **Comment storage location.** `data/comments.jsonl` alongside `data/votes.json`, or a
   field on the row. Field-on-row makes a row with six comments a fat blob in every lookup;
   sibling file costs a join and a second fetch in the static fallback. **Leaning sibling
   file**, because the export gets a second file which the static path can tolerate, and
   the agent payload should carry only *promoted* content anyway.
4. **Anonymous comments at launch or v2?** Recommendation was v2 — vote anonymously at
   launch, comment with a handle, let friction be a filter while there is one moderator.
   Not agreed.
5. **What a human sees at a `not-searched` URL.** D15 says it must give them the "here's
   where to check, log it when you're done" loop. Not designed, not built.
6. **Whether `untested` actually resolves true at a useful rate.** Unmeasurable until rows
   exist. If ~85% of untested claims resolve to `solved`, `untested` is a trustworthy prior
   and should be surfaced loudly. If ~40%, it needs a caveat. Track it from the first rows.

---

## 4. What to do before the move, in order

Cheapest-highest-value first. Everything below is a small change; none is a redesign.

1. **`_hint()` / payload says "proposed, unverified" for `untested`** (D8). Highest
   severity — the only failure in this spec that actively misleads.
2. **`STATUSES` + invariant 4 rewrite** in `pipeline/schema.py` (2.1). Without this,
   `pipeline/build.py --check` keeps enforcing the old state list and any `untested` row
   fails CI, which means nobody can land one.
3. **`CONTRIBUTING.md` response-time line** (2.4). Five lines. Prevents the repo reading as
   abandoned during the move.
4. **Issue template** (2.4). Ten minutes.
5. **Then and only then:** variant fields in the schema (2.1) — larger, and the first four
   are what make everything above contribute-able.

Explicitly out of scope until after the move: the comment table, the promotion path, the
forum, the three-button contribution form, `fits` UI, the `not-searched` page. The data
model must *permit* them; building them now is how the move derails.

---

## 5. Provenance

Design session 2026-11-22 ~15:37–16:07 EST. Draws on the vault note
`00 My Notes/Kernel index — hardware × model × engine.md` (four-state model, wanted-not-
bounty, negative space) and the existing `CONTRACT.md` / `README.md` data-honesty model
(`source_kind: derived` → the same warning discipline applied to `untested`).

Two positions were corrected during the session and the corrections are retained in D15
(agent-forward, not agent-only) and D16/D17 (licence work was unnecessary — MIT, public
repo, and CI already existed). Both corrections came from reading the repository rather
than reasoning about it.
