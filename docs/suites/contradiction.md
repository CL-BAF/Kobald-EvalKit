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
  invisible (verified: a fully-paraphrased attribution swap escapes the
  pairs). This is the conservative design; semantic judgement stays
  needs_human elsewhere.
- The pairs catch BLENDING, not wrong-value-only repetition: a response
  that repeats only the misstatement passes the pair check (one side only).
  That residual is visible in the fixture matrix as a known-pass-with-caveat,
  and is a documented boundary, not a defect.
- Pair re-tuning during landing removed cross-case false-positive pairs
  (Reviewer's collision procedure applied in-flight).