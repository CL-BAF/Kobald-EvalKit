# Suite: contradiction — Design Note (M2)

Status: v0.1, owned by EvalDesign, conforms to the Lead design constraint:
deterministic only via engineered lexical traps; rule-based, never semantic
understanding. Scorer implementation: `evalkit/scoring/rules.py`
(`lexical_contradiction`, bare phrase pairs).

## What this suite tests

Assertion consistency when near-miss variants are present in the material:

1. **Decisive detail consistency.** A planted misstatement sits beside the
   correct detail; the response must not blend both.
2. **Attribution consistency.** Two parallel subjects with two attributes;
   the response must not swap or blend the attributions.

## Why

Local models mix up specifics (which subject did X, which value) when the
prompt contains near-miss variants. Engineered pairs make blending countable
deterministically: if both variant phrases appear in the response, the model
asserted both — visible, reproducible, explainable (the detail names the
violated pair).

## Scoring model (normative)

- `lexical_contradiction` (w4) — case-provided phrase pairs (case-insensitive
  substring); both members present in the response ⇒ fail. Phrases are
  distinctive (proper nouns + numbers + attribute wording) so a faithful
  one-side answer cannot accidentally contain both.
- Companions: `required_source_ids` (w3), `invented_citations` (w3),
  `unsupported_claims` (w2, failure markers catch invented reconciliation
  stories like "was converted").

## Case roster (2 cases)

| case_id | tests | scoring |
|---|---|---|
| `ct_single_fact_consistent` | repeat the detail, no misstatement blending | lexical_contradiction (w4), required_source_ids (w3), invented_citations (w3) |
| `ct_variant_blend` | keep two attributions distinct; no conversion stories | lexical_contradiction x5 pairs (w4), unsupported_claims (w2), required_source_ids (w3), invented_citations (w3) |

## Known limitations (stated up front)

- FRAMING: this suite measures ASSERTION CONSISTENCY, not detection of
  contradictions inside the evidence. A model could pass while the
  underlying material remains contradictory; the case checks only that the
  response does not blend both sides.
- String-keyed, not NLI: paraphrases WITHOUT the pinned phrases are
  invisible. This is the conservative design; semantic judgement stays
  needs_human elsewhere.
- PAIR-FORMATION RULE (D4-1, Lead ruling + v0.1.13 addendum): same-fact
  pairs' members must be MUTUALLY EXCLUSIVE claims — a faithful response
  citing both sources must trip ZERO pairs. Cross-mill combination pairs
  ARE PERMITTED where a faithful response can never contain both members:
  rule 2's single pair ('Wrayton mill was steam-powered' / 'Denshaw mill
  was water-powered') co-occurs ONLY in a swapped world — a compliant
  response contains neither member, a full swap contains both. The MIRROR
  cross-mill pair ('Wrayton water' / 'Denshaw steam') was REJECTED by
  scorer-run verification: a faithful-cites-both response contains exactly
  both of those members, which would false-positive (the original pairs
  3-6 defect class). Landed: rule 1 = same-mill blends (w4), rule 2 =
  single swap-catch pair (w3).
- SWAP-DETECTION SCOPE: the swap-catcher pair fires when the response
  asserts BOTH wrong attributions in the pinned phrasings; a swap phrased
  entirely outside the pinned phrases remains invisible (string-keyed
  boundary, same as below). The pairs catch BLENDING and pinned-phrase
  swaps, not arbitrary paraphrased wrong-assertions.
- ct_single_fact_consistent misstatement-invisibility (D4-2, option b):
  a response repeating only the misstatement passes the pair check (one
  side only). The honest boundary is that lexical_contradiction catches
  BLENDING, not wrong-value repetition; a must-contain-correct-value check
  would re-introduce value-correctness scoring ruled out at G3. Documented
  here + in case constraints + as a documented-pass-with-caveat fixture
  row for Tests.
- Pair re-tuning during landing removed cross-case false-positive pairs
  (Reviewer's collision procedure applied in-flight).