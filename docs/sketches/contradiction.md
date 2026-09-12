# Suite Sketch: contradiction (M2, wave 4/5)

Status: docs-only sketch (M1 review window; suites/ landings wait for
gate-clear). Conforms to the Lead design constraint: deterministic only via
engineered lexical traps; rule-based, never semantic understanding. Scorer:
`lexical_contradiction` (landed, `evalkit/scoring/rules.py:165-193`; params
`{"pairs": [[claim_a, claim_b], ...]}` — case-insensitive substring, both
members present ⇒ fail).

## What this suite tests

1. **Self-consistency under loaded context.** Given a passage containing a
   decisive detail, the model repeats the detail consistently (right value,
   not its trap-variant).
2. **Paraphrase resistance (lexical level).** The model does not blend the
   detail with a superficially similar-but-contradictory variant present in
   the surrounding material.

## Why

Local models mix up specifics (which of two people did X, which year, which
direction) when the prompt contains near-miss variants. Engineered pairs make
the blend countable deterministically: if both variant phrases appear in the
response, the model asserted both — visible, reproducible, explainable.

## Case designs (2 cases, landing post-gate)

### ct_single_fact_consistent

- Setup: excerpt where the fictional Wrayton mill's 1911 output is stated as
  "eleven thousand spindles" in one clause and a NEAR-MISS distractor clause
  mentions "eleven thousand looms is sometimes misreported" (a deliberately
  planted misstatement the instruction flags as unreliable).
- Instruction: "State the mill's 1911 spindle count as given. Do not repeat
  the misreported figure."
- Scoring: `lexical_contradiction` with pairs
  `[["eleven thousand spindles", "eleven thousand looms"]]` — a response
  asserting both fails; the detail names the pair.
- Companion `no_absolute_claims` (default phrases).
- Weight: contradiction=4, absolutes=2.

### ct_variant_blend

- Setup: two excerpt paragraphs about two fictional mills (Wrayton: water-
  powered; Denshaw: steam-powered). Instruction: answer which mill is
  water-powered and which is steam-powered in one sentence.
- Scoring: `lexical_contradiction` pairs
  `[["Wrayton was water-powered", "Wrayton was steam-powered"],
    ["Denshaw was steam-powered", "Denshaw was water-powered"]]` — blending
  the attribution either way trips a pair.
- Companion `unsupported_claims` (failure markers: ["was converted",
  "was later converted"] — the excerpts contain no conversion events; a
  model reconciling the two mills by inventing a conversion fails).
- Weight: contradiction=4, unsupported=2.

## Honest limits (stated in suite doc when landed)

- FRAMING REQUIREMENT (Lead, landing requirement): each case's purpose field
  must state explicitly that the test measures ASSERTION CONSISTENCY — not
  detecting contradictions IN the evidence. A model could pass while the
  underlying evidence pair remains contradictory; the case checks only that
  the response does not blend both sides. This framing keeps the benchmark
  claim honest.
- The scorer is string-keyed, not NLI: paraphrases WITHOUT the pinned phrases
  are invisible (docs/scoring.md limitation). Cases use distinctive,
  hard-to-paraphrase phrases (proper nouns + numbers) so a faithful answer
  to one side cannot accidentally contain both.
- The trap is ENGINEERED, so a model that fully re-derives facts can still
  pass while being subtly wrong in unmeasured ways — stated, not hidden.
- Both-pair-members-present is a CONSERVATIVE test: it only fires on actual
  lexical blending, never on mere verbosity.

## Fixture plan for Tests (post-gate)

- compliant: states the correct variant once, no distractor phrase.
- fail/blend: contains both pair members (trips pair, detail names it).
- fail/invented-conversion (ct_variant_blend): correct attribution + invented
  conversion clause → unsupported_claims fails, contradiction passes.