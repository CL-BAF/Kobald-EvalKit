# EvalKit Case Schema v0.1

Status: v0.1, ratified through contract Amendments v0.1.1-v0.1.7 (Lead-issued).
This document is normative for the case loader (Core) and for all case files in
`suites/` (EvalDesign). A JSON-Schema-style reference lives in
`docs/case-schema.json`.

Every evaluation case is one JSON file in `suites/<suite>/<case_id>.json`. The
filename stem MUST equal `case_id` (loader rejects mismatches). Optional
per-suite metadata lives in `suites/<suite>/suite.json` (informational only;
never a scoring source). Case files are JSON (UTF-8, no BOM). Unknown
top-level keys are strictly rejected by the loader (typo safety).
`suite` must match the parent directory name; suite directories outside the
v0.1 registry are rejected. Duplicate `case_id` across files is rejected,
naming both files. Loader-rejected cases abort the run with exit 1; they never
enter `result.json` (Amendment v0.1.4: no "skipped" status).

## Design principles

1. **Deterministic or flagged.** Every check either computes a definite
   pass/fail from the response text and case data, or is marked
   `needs_human: true`. EvalKit never produces a fake number for fuzzy
   judgement.
2. **Single source of truth.** `scoring[].params` drives enforcement. The
   `expected` and `constraints` fields are documentation for humans; scorers
   MUST NOT read them (Amendment v0.1.2 #5). This prevents drift between
   prose and enforcement.
3. **Redistributable content.** All evidence is invented (fictional studies,
   bodies, places). Nothing derived from private projects. Safe under MIT.
4. **Explainable.** Each check reports what it counted and what the limit was.
   A reader of `result.json` can see exactly why a case passed or failed.

## Top-level fields

| field | type | required | notes |
|---|---|---|---|
| `schema_version` | string | no (default `"1"`) | only `"1"` accepted in v0.1 (Amendment v0.1.2 #1) |
| `case_id` | string | yes | `^[a-z][a-z0-9_]{0,63}$`; must equal filename stem |
| `suite` | string | yes | `^[a-z][a-z0-9_]*$`; matches parent directory name |
| `title` | string | yes | 1-200 chars, human-readable |
| `purpose` | string | yes | 1-2000 chars; MANDATORY and meaningful: what behaviour is tested and why it matters |
| `evidence` | array | yes (may be empty for some suites) | items: `{"id": string, "text": string}`; `id` matches `^[A-Z0-9][A-Z0-9-]{1,23}$` (uppercase so citation-token mismatches are detectable), unique within the case (loader-enforced); `text` 1-4000 chars |
| `instruction` | string | yes | sent to the model VERBATIM as the user turn; MUST be self-contained (references evidence by ID, includes format rules) |
| `constraints` | string | yes | human-readable summary of a compliant response; never machine-enforced |
| `scoring` | array | yes, 1-8 items | see below |
| `expected` | string | yes | DOCUMENTATION-ONLY sketch of a good response for human review; loader ignores it for scoring (Amendment v0.1.2 #5) |

### `scoring[]` item

| field | type | required | notes |
|---|---|---|---|
| `type` | string | yes | registered scorer name (see docs/scoring.md); unknown types rejected by loader |
| `params` | object | yes | parameters for that scorer; the ONLY enforcement source |
| `weight` | number (float) | no (default 1.0) | Amendment v0.1.3 #6: optional, default 1.0. v0.1 cases use integer values 1-5 as an ordinal-emphasis convention; values outside 0.5-5 are rejected. Used ONLY for reported aggregates, NEVER for pass/fail |

## Frozen scoring semantics (Amendments v0.1.2 #4, v0.1.3 #4/A2, v0.1.7 #1)

### Check object

- `name: str`, `passed: bool`, `detail: str`, `count: int | None`
  (None = non-counting check), `needs_human: bool` (optional, default false).

### Semantics

- A `needs_human` check always reports `passed = false` with detail explaining
  that automation was insufficient. It never silently passes and never
  silently fails the case; it is **excluded from aggregates**.
- `ScoreResult.passed` = **every** non-`needs_human` check passed.
- `ScoreResult.needs_human` = true iff ANY check has `needs_human = true`.
- `CaseResult.passed` = `ScoreResult.passed` AND NOT
  `ScoreResult.needs_human`.
- `CaseResult.status` enum (exactly): `"passed" | "failed" | "needs_human" |
  "error"`. Derivation (Amendment v0.1.3 #6, v0.1.4 #2): generation failure ->
  `"error"`; else `score.needs_human` -> `"needs_human"`; else
  passed/failed from `CaseResult.passed`. Every started case appears in
  `results` — including error cases — so compare denominators stay stable.
- `weight` (float, default 1.0) is used only for human-readable aggregate
  reporting: `weighted_pass_rate = sum(weight of passed cases) / sum(weights
  of all scored cases)`, averaged over non-`needs_human` cases only; cases
  needing human review are listed separately, never averaged in. Formula and
  limitations live in `docs/scoring.md` (and must appear in scoring module
  docstrings and README before M2 per Amendment v0.1.2 #4).

## Versioning (Amendment v0.1.2 #1)

Case files may carry `schema_version` (default `"1"` when absent). Loader
rejects unknown versions with an actionable message. Future versions bump this
field; `compare` refuses to compare across schema versions.

## Implementation constraint (normative for Core)

All case validation is hand-rolled stdlib validation. The `$schema` / `$id`
members of `docs/case-schema.json` are inert identifiers: the loader MUST NOT
fetch, resolve, or process any URL found in case files or schema files. There
is no network in evaluation, ever.

## Suite registry (v0.1)

| suite | status | notes |
|---|---|---|
| `evidence_grounding` | M1 | citation presence / no invented sources / claim hygiene |
| `contradiction` | M2 | rule-based lexical traps only; never semantic understanding |
| `fabricated_citations` | M2 | plausible-but-absent citation patterns |
| `structured_output` | M2 | valid JSON + field contracts |
| `uncertainty` | M2 | exact-marker convention (see docs/scoring.md) |
| `mixed_evidence` | M2 | surface checks only; judgment core is needs_human |

Suite names are directories under `suites/`. A case's `suite` field must match
its directory. The list above is the v0.1 registry; unknown suite directories
are rejected by the loader.