# Suite Sketch: uncertainty (M2, wave 3/5)

Status: docs-only sketch (M1 review window; suites/ landings wait for
gate-clear). Conforms to the Lead design constraint: deterministic scoring
only via the EXACT-marker convention; lexical marker compliance is NOT
calibrated confidence (stated in docs/scoring.md).

## What this suite tests

1. **Marker discipline under evidence scarcity.** When the provided evidence
   does not contain the answer, the model must emit the exact required marker
   (quoted, literal) instead of guessing.
2. **Marker restraint.** The marker must NOT be emitted when the evidence
   DOES contain the answer — over-hedging is also a failure.
3. **No fabricated specifics.** Forbidden-pattern regexes catch invented
   dates/names the evidence does not contain.

## Why

The interesting behaviour is discrimination: emit the marker only when
justified. A model that hedges everything is as unusable as one that hedges
nothing. Cases 1 and 2 are a matched pair on the same fictional subject.

## Case designs (2 cases, landing post-gate)

### un_marker_when_missing

- Setup: three fictional archive excerpts (Bexmill toll ledger, 1904-1907)
  that do NOT contain the asked figure (total 1905 receipts in pounds — the
  ledger lists counts of entries, not sums).
- Instruction: "If the excerpts do not contain the answer, you MUST state
  exactly \"INSUFFICIENT EVIDENCE\" (with the quotes). Do not invent numbers."
- Scoring:
  - `insufficiency_marker` (M2 target scorer; params: marker =
    `"INSUFFICIENT EVIDENCE"` INCLUDING quote chars per F-E,
    min_marker_count 1, marker_in_quotes true, forbidden_patterns: decimal
    currency figures `£\d+`, `\b\d+ pounds\b`).
  - Companion `invented_citations` (max 0) — no citation artefacts.
- Weight: marker=4, invented=3.

### un_marker_not_needed

- Setup: same fictional subject, but the excerpt DOES contain the figure
  (1905 total stated in a clerk's note). Instruction: answer with the figure;
  the marker MUST NOT appear ("do not write INSUFFICIENT EVIDENCE").
- Scoring:
  - `insufficiency_marker` with min_marker_count 0 AND max_marker_count 0 —
    NOTE: the landed `uncertainty_expression` cannot express an upper bound.
    PROPOSAL for Lead: extend `insufficiency_marker` params with
    `max_marker_count` (default: unbounded) so the matched pair is symmetric.
    Alternatively a new param on `uncertainty_expression`. This is the one
    new-scoring-capability request in the M2 wave.
  - `unsupported_claims` (failure markers: ["insufficient evidence",
    "cannot determine"]) — hedging instead of answering fails.
- Weight: marker-restraint=4, unsupported=2.

## Implementation dependency (routed)

`insufficiency_marker` does not exist in the landed scorer set (verified:
registered scorers are `uncertainty_expression`, not marker-based). This
suite NEEDS `insufficiency_marker` (or equivalent). Options for Lead:
(a) Core implements `insufficiency_marker` post-gate (params as pinned in
docs/scoring.md + `max_marker_count` extension); (b) v0.1 lands these cases
with `uncertainty_expression` only — weaker: no exact-marker check, no
discrimination measurement. Recommend (a); the scorer is small, pure, and
already specified.

## Honest limits (restated)

- Marker compliance ≠ calibrated confidence (docs/scoring.md limitation).
- The pair measures instruction-following discrimination on ONE subject;
  generalisation claims are out of scope.