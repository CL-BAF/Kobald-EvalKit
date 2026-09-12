# Suite Sketch: mixed_evidence (M2, wave 5/5)

Status: docs-only sketch (M1 review window; suites/ landings wait for
gate-clear). Conforms to the Lead design constraint: surface checks only;
the judgment core is ALWAYS needs_human via the `conflict_assessment`
companion; every case in this suite reports needs_human=true BY DESIGN and is
excluded from weighted aggregates (docs/scoring.md, F-B).

## What this suite tests

1. **Both sides engaged.** The response cites every provided source (surface
   check: `all_sources_present`).
2. **Placeholder hygiene.** No unresolved template placeholders left behind
   (`unresolved_marker`, landed meaning: patterns must NOT appear).
3. **No overconfident synthesis.** No absolute-confidence phrases
   (`no_absolute_claims`).
4. **Judgement flagged, not faked.** `conflict_assessment` companion marks
   the actual weighing for human review.

## Why

Contradictory sources are the real-world RAG condition. We CANNOT honestly
automate "weighed the evidence well" (keyword-bingo risk — Lead constraint).
What we CAN measure mechanically is whether the model engaged with all
sources and avoided overconfidence; the quality of the weighing itself is
needs_human. The suite's value is the pairing: surface compliance is
countable, and the result honestly says the reasoning part needs a human.

## Case designs (2 cases, landing post-gate)

### me_two_sources_conflict

- Setup: two fictional excerpts that disagree on a date (the fictional
  Ashcomb library fire: board minutes say 1923; a later newspaper retrospective
  says 1926). Instruction: "Summarize what the sources say about the fire,
  noting that they disagree. Do not declare which is correct."
- Scoring: `all_sources_present` (w3), `unresolved_marker` (defaults),
  `no_absolute_claims`, `conflict_assessment` (instructions: "judge whether
  the response represents both dates fairly and refrains from
  adjudicating").
- ALL cases carry conflict_assessment ⇒ whole suite is needs_human=true by
  design; surface checks still run and their counts appear in details.

### me_conflict_with_resolution_marker

- Setup: same two excerpts plus a third (insurance register 1924 entry
  consistent with the 1923 date). Instruction: "If one source is better
  supported than the other, say so briefly; otherwise write UNRESOLVED."
- Scoring: as above; `unresolved_marker` patterns extended with
  `UNRESOLVED` (the required marker appears when present — the scorer
  checks placeholders are ABSENT; the marker word UNRESOLVED in prose is
  content, verified via `unsupported_claims` failure markers? No — see
  dependency note).

## Dependency note (RULED: option a, Lead)

The landed `unresolved_marker` scorer checks that placeholders (like
`<PLACEHOLDER>`) are ABSENT; it cannot require the WORD "UNRESOLVED" to be
PRESENT. RULED for v0.1: option (a) — drop the mechanical presence-check;
every mixed_evidence response gets human review anyway (conflict_assessment
makes the whole suite needs_human by design), so a mechanical marker check
adds nothing. The instruction still asks for the marker; its presence is
judged by the human reviewer, stated in the case doc. Reuse of
insufficiency_marker with max_marker_count stays available as the v0.2 path
(mechanical enforcement later) — filed in the existing v0.2 change note
(docs/changes/v02-proposed-insufficiency-marker.md), not a second note.

## Honest limits (restated)

- This suite measures ENGAGEMENT and HYGIENE, not reasoning quality (README
  limitation per Lead).
- All cases are needs_human=true BY DESIGN; a run containing only
  mixed_evidence reports "no scoreable cases — all need human review"
  (F-D display rule) and no weighted rate. That is the honest reading.