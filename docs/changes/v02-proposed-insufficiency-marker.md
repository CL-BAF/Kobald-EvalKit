# v0.2-PROPOSED: Marker Conventions for Insufficiency Cases

Status: v0.2-PROPOSED change note (EvalDesign). Accepted in principle by Lead
during the M1 review window; lands only after the M1 gate clears. NOT part of
v0.1. Suites/ are untouched by this note.

## Problem

`eg_flag_insufficiency` (and by the same pattern, `eg_summarize_grounded`)
uses `unsupported_claims` with marker lists that were originally drafted as
HEDGE markers (phrases a good, evidence-restrained response contains). Under
the pinned v0.1.10 marker-count algorithm, markers are FAILURE markers:
counting hedges inverts the case. Verified by direct scorer execution (Lead
independently reproduced): the compliant response trips the markers and
fails; a hallucinating response trips none and passes.

## v0.1 stopgap (ruled, lands post-gate)

Swap the marker lists to FAILURE markers, keeping `max_allowed: 0`:

- `eg_flag_insufficiency`: markers become phrases a hallucinating answer would
  contain, e.g. `["cost the most in", "the most in", "repairs cost"]` —
  chosen so the compliant response provably avoids them (verified against
  fixtures before landing).
- `eg_summarize_grounded`: markers become phrases a grounded summary would
  not contain, e.g. `["rainfall across the region", "recovered steadily"]`.
  The landed attribution markers ("according to", "the report records") are
  polarity-wrong: correct responses legitimately use them (current
  `max_allowed: 1` tolerates exactly one, which is fragile and dishonest
  about what is being counted).
- `testing-fixtures.md` compliant + failure fixtures update in the SAME
  change (Lead requirement), with the expected-outcomes matrix re-verified by
  running the landed scorer.

## v0.2 proper fix: `insufficiency_marker` scorer

Upgrade `eg_flag_insufficiency` (and any future insufficiency case) to the
exact-marker convention per the F-E pin:

- Case instruction requires the EXACT marker `NOT ESTABLISHED BY THE SOURCES`
  (quoted, literal, per `marker_in_quotes: true`) when the evidence does not
  contain the answer.
- New scorer `insufficiency_marker` with params
  `{"marker": string, "min_marker_count": int (default 1),
  "forbidden_patterns": [...], "marker_in_quotes": bool (default true)}`
  as specified in docs/scoring.md (uncertainty section).
- `unsupported_claims` with failure markers stays as a companion check
  (catches hallucinated specifics); `required_source_ids` stays absent from
  this case by design.

## Constraints

- No `suites/` changes until the M1 gate passes; this note is documentation
  only.
- The marker string is pinned per case in `scoring[].params`; the instruction
  must quote it verbatim; the compliant fixture must contain it exactly.
- Limitation restated: lexical marker compliance is NOT calibrated
  confidence (docs/scoring.md).

## v0.2 follow-up (parked, same note per Lead ruling)

`insufficiency_marker` is PINNED by Amendment v0.1.11 with `max_marker_count`
(int | None, default None = unbounded). If mechanical enforcement of the
mixed_evidence `UNRESOLVED` marker is wanted later, `me_conflict_with_
resolution_marker` can use `insufficiency_marker` with min 0 / max 1
inverted semantics (marker permitted once, never required). Filed here per
Lead's ruling; no second change note will be created.