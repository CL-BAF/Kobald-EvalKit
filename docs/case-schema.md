# EvalKit Case Schema v0.1

Status: proposed by EvalDesign, v0.1, 2026-09-12. Pending Lead sign-off at R-contracts.

Every evaluation case is one JSON file in `suites/<suite>/<case_id>.json`. The
filename stem MUST equal `case_id`. Optional per-suite metadata lives in
`suites/<suite>/suite.json` (informational only; the loader never reads it for
scoring). Case files are JSON (UTF-8, no BOM). Unknown top-level keys are
rejected by the loader (typo safety). `schema_version` accepts only `"1"` in
v0.1.

## Design principles

1. **Deterministic or flagged.** Every check either computes a definite
   pass/fail from the response text and case data, or is marked
   `needs_human: true`. EvalKit never produces a fake number for fuzzy
   judgement.
2. **Single source of truth.** `scoring[].params` drives enforcement. The
   `expected` and `constraints` fields are documentation for humans; scorers
   MUST NOT read them. This prevents drift between prose and enforcement.
3. **Redistributable content.** All evidence is invented (fictional studies,
   bodies, places). Nothing derived from private projects.
4. **Explainable.** Each check reports what it counted and what the limit was.
   A reader of `result.json` can see exactly why a case passed or failed.

## Top-level fields

| field | type | required | notes |
|---|---|---|---|
| `schema_version` | string | no (default `"1"`) | only `"1"` accepted in v0.1 |
| `case_id` | string | yes | `^[a-z][a-z0-9_]*$`, 1-64 chars, must equal filename stem |
| `suite` | string | yes | `^[a-z][a-z0-9_]*$`; matches parent directory name |
| `title` | string | yes | 1-200 chars, human-readable |
| `purpose` | string | yes | 1-2000 chars; MANDATORY and meaningful: what behaviour is tested and why it matters |
| `evidence` | array | yes (may be empty for some suites) | each item: `{"id": string, "text": string}`; `id` matches `^[a-z][a-z0-9_]*$`, unique within the case; `text` 1-4000 chars |
| `instruction` | string | yes | sent to the model verbatim as the user turn; MUST be self-contained (references evidence by ID, includes format rules) |
| `constraints` | string | yes | human-readable summary of what a compliant response looks like; never machine-enforced |
| `scoring` | array | yes, 1-8 items | see below |
| `expected` | string | yes | documentation-only sketch of a good response; never read by scorers |

### `scoring[]` item

| field | type | required | notes |
|---|---|---|---|
| `type` | string | yes | registered scorer name (see docs/scoring.md) |
| `params` | object | yes | parameters for that scorer; the ONLY enforcement source |
| `weight` | integer | yes | 1-5; used for reported aggregates only, never for pass/fail |

## Frozen scoring semantics (R4)

- A check has `name`, `passed`, `detail`, and (optional) `count`.
- `ScoreResult.passed` = **all** non-`needs_human` checks passed.
- `ScoreResult.needs_human` = true iff any check was marked `needs_human`.
- A `needs_human` check always reports `passed = false` with detail explaining
  that automation was insufficient; it is **excluded from aggregates** and never
  silently passes or fails the case.
- `weight` (integer 1-5) is used only for human-readable aggregate reporting.
  The documented aggregate for a run is
  `weighted_pass_rate = sum(weight of passed cases) / sum(all weights)` over
  **non-needs_human cases only**; cases needing human review are listed
  separately, never averaged in. Formula and limitations live in
  `docs/scoring.md`.

## Versioning (R1)

`suite.json` and case files may carry `schema_version` (default `"1"`). Loader
rejects unknown versions with an actionable message. Future versions bump this
field; `compare` refuses to compare across schema versions.

## Suite registry (v0.1)

| suite | status |
|---|---|
| `evidence_grounding` | M1 |
| `contradiction` | M2 |
| `fabricated_citations` | M2 |
| `structured_output` | M2 |
| `uncertainty` | M2 |
| `mixed_evidence` | M2 |

Suite names are directories under `suites/`. A case's `suite` field must match
its directory. The suite list above is the v0.1 registry; unknown suite
directories are rejected by the loader.