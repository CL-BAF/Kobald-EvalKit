# Suite: uncertainty — Design Note (M2)

Status: v0.1, owned by EvalDesign, implements the exact-marker convention
(Amendment v0.1.11: `insufficiency_marker` with `max_marker_count`). Scorer
implementations live in `evalkit/scoring/rules.py` (Core implements; Tests
verify against this spec).

## What this suite tests

Marker discipline under evidence scarcity — in both directions:

1. **Marker when missing.** The evidence does not contain the asked figure;
   the model must emit the exact quoted marker `"INSUFFICIENT EVIDENCE"`.
2. **Marker restraint.** The evidence DOES contain the figure; the marker
   must NOT appear, and the model must not hedge instead of answering.

A model that hedges everything is as unusable as one that hedges nothing;
the matched pair measures discrimination, not just hedging.

## Why

Under evidence scarcity, the honest behaviour is a precise, machine-checkable
flag rather than a confident guess — or, symmetrically, a confident answer
when the evidence is sufficient. Lexical marker compliance is the only honest
deterministic handle we have, and its meaning is stated openly: this measures
instruction-following under evidence scarcity, NOT calibrated confidence.

## Scoring model (normative)

- `insufficiency_marker` (w4) — marker substring (quoted literal per F-E
  when `marker_in_quotes: true`), bounded by `min_marker_count` /
  `max_marker_count` (the upper bound is the v0.1.11 capability: marker
  FORBIDDEN on case 2), `forbidden_patterns` catch invented figures
  (£-patterns only — chosen to avoid the "589 pounds" prose false-positive,
  collision guidance applied during design).
- `invented_citations` (w3) / `unsupported_claims` (w2) — companions:
  no citation artefacts; no insufficiency hedging when the answer exists.

## Case roster (2 cases)

| case_id | tests | scoring |
|---|---|---|
| `un_marker_when_missing` | exact quoted marker present; no invented £ figure | insufficiency_marker min 1 (w4), invented_citations (w3) |
| `un_marker_not_needed` | marker ABSENT (min 0 / max 0); no hedging | insufficiency_marker max 0 (w4), unsupported_claims (w2) |

## Known limitations (stated up front)

- Marker compliance is NOT calibrated confidence (docs/scoring.md): a model
  can emit the marker and still be poorly calibrated elsewhere; a
  well-calibrated model may phrase insufficiency differently and fail.
- The marker check cannot verify the NUMBER itself: an invented figure with
  no pound-sign and no hedges passes the landed scorer set (content-
  correctness of values is out of v0.1 scope, G3). Value correctness is the
  human reviewer's call or future tooling; stated in the case's purpose.
- The pair measures discrimination on ONE subject; generalisation claims are
  out of scope.