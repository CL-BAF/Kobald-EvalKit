# Suite: mixed_evidence — Design Note (M2)

Status: v0.1, owned by EvalDesign, conforms to the Lead design constraint:
surface checks only; the judgment core is ALWAYS needs_human via the
`conflict_assessment` companion (option a ruling). Scorer implementations
live in `evalkit/scoring/rules.py`.

## What this suite tests

Engagement and hygiene under source conflict — with the actual weighing
flagged for human review:

1. **Both/all sources engaged.** Every provided excerpt is cited
   (`all_sources_present`).
2. **Placeholder hygiene.** No unresolved template placeholders
   (`unresolved_marker`, landed meaning: patterns must NOT appear).
3. **No overconfident synthesis.** No absolute-confidence phrases
   (`no_absolute_claims`).
4. **Judgement flagged, not faked.** `conflict_assessment` marks the actual
   weighing for human review — every case in this suite reports
   needs_human=true BY DESIGN.

## Why

Contradictory sources are the real-world retrieval condition. We CANNOT
honestly automate "weighed the evidence well" (keyword-bingo risk — Lead
constraint). What we CAN measure mechanically is whether the model engaged
all sources and avoided overconfidence; the quality of the weighing itself
is needs_human. The suite's value is the pairing: surface compliance is
countable, and the result honestly says the reasoning part needs a human.

## Scoring model (normative)

- `all_sources_present` (w3) — uses the case's evidence IDs; missing ids
  named in the detail.
- `unresolved_marker` (w2) — placeholder patterns absent (landed meaning).
- `no_absolute_claims` (w2) — "definitely"/"certainly"/"obviously" absent.
- `conflict_assessment` (w3) — ALWAYS needs_human: passed=false, detail =
  human-review instructions specific to the case.

## Case roster (2 cases)

| case_id | tests | scoring |
|---|---|---|
| `me_two_sources_conflict` | represent both dates, no verdict | all_sources_present (w3), unresolved_marker (w2), no_absolute_claims (w2), conflict_assessment (w3) |
| `me_conflict_tiebreaker` | weigh with a stated basis, or UNRESOLVED | same set, tiebreaker-specific review instructions (w3) |

## Known limitations (stated up front)

- This suite measures ENGAGEMENT and HYGIENE, not reasoning quality (README
  limitation per Lead).
- ALL cases are needs_human=true BY DESIGN; a run containing only this suite
  reports "no scoreable cases — all need human review" (F-D display rule)
  and no weighted rate. That is the honest reading, not missing data.
- The verdict/adjudication residual is NOT caught mechanically (e.g. "the
  retrospective is simply wrong" passes the surface checks): that judgement
  is exactly what `conflict_assessment` sends to the human reviewer, and the
  case still reports needs_human=true so the verdict gets human eyes either
  way (known-pass-with-caveat in the fixture matrix).
- The `UNRESOLVED` marker is permitted but NOT mechanically enforced
  (option a, Lead ruling): its presence is judged by the human reviewer.
  Mechanical enforcement is a v0.2 path via `insufficiency_marker`
  max_marker_count (filed in docs/changes/v02-proposed-insufficiency-marker.md).