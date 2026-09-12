# Scoring Rules v0.1 — How EvalKit Scores

Status: owned by EvalDesign. This document is normative for scorer
implementations in `evalkit/scoring/*` and for the aggregate formulas used by
`run` / `report` / `compare`.

## Two kinds of checks

**Deterministic checks** compute a definite pass/fail from the response text
and case parameters. Same response + same case ⇒ same result, forever. Counts
and limits appear in `check.detail` so a human can verify the arithmetic.

**needs_human checks** cover judgement we refuse to fake (e.g. "is this
paraphrase actually faithful to the evidence?"). They are emitted with
`passed = false`, `needs_human = true`, and a detail explaining what a human
should look at. They never tip a case to passed or failed on their own.

## Frozen semantics (R4)

- `ScoreResult.passed` = all non-`needs_human` checks passed.
- `ScoreResult.needs_human` = true iff any check is `needs_human`.
- `weight` (1-5, integer) affects **reported aggregates only**, never
  pass/fail. A case that fails its only check is a failed case at any weight.

## Run aggregate (the only one in v0.1)

```
weighted_pass_rate = sum(weights of passed cases) / sum(weights of all scored cases)
```

- Averaged over **non-`needs_human` cases only**. Cases with
  `needs_human = true` are listed separately ("X cases need human review"),
  never averaged in.
- Documented limitations: (1) weights are ordinal design choices, not measured
  importance — they exist so users can emphasise suites, not as a scientific
  quantity; (2) cases are small behavioural probes, not a representative
  sample of any population; (3) rates from different model sizes, quantisations
  or option sets are not comparable unless the user controls those variables.
- No overall "score" number is published. Reports show pass/fail counts, the
  weighted pass rate, and per-check details.

## Registered scorer types (v0.1)

Params below are normative. `expected`/`constraints` in a case are never read
by scorers.

### evidence_grounding suite

**`required_source_ids`** — params: `{"ids": [...], "allow_extras": bool}`.
Citation tokens in the response are extracted with a strict regex (see
"citation tokens"). Check passes iff every ID in `ids` appears at least once
and, if `allow_extras` is false, no other source IDs from the case's `evidence`
appear. Non-evidence IDs found in the response are counted and reported by
`invented_citations` (below); this check never fails on them alone.
Deterministic: yes.

**`invented_citations`** — params: `{"max_allowed": int, "ids": [...]}`.
Counts citation tokens in the response that are not in `ids` (the case's
legitimate evidence IDs, optionally with the `allow_extras` rule applied by
`required_source_ids` — here the rule is absolute: tokens not in `ids` count as
invented). Passes iff invented count ≤ `max_allowed`. Deterministic: yes
(regex counting; see token format caveats below).

**`unsupported_claims`** — params: `{"max_allowed": int, "markers": [...]}`.
Deterministic *marker* scoring, not semantic scoring: counts claim statements
that cite no evidence ID and are not hedge-protected. Splitting is a heuristic
(see caveats); to keep it honest, this check also sets `needs_human = true`
when the response contains zero citation tokens at all but is longer than a
short freeform (≥ `min_length`, default 200 chars) — i.e. we could not verify
anything mechanically. Passes iff claims ≤ `max_allowed` **and** no
needs_human was raised. Deterministic: yes as a marker count; the semantic
"supported" judgement is explicitly out of scope.

### Citation token format (normative for extractors)

A citation token is `[` + one or more uppercase letters, digits, or hyphens,
length 2-24, `]` — e.g. `[SRC-01]`, `[GEO-2]`. Regex:
`\[[A-Z0-9][A-Z0-9-]{1,23}\]`. Tokens are extracted from the raw response
text. Two caveats, always stated in reports: (1) a model that cites as
"(SRC-01)" or "Source 1" produces no tokens — the check fails visibly and the
detail says so (an honest format failure, not a silent zero); (2) IDs are
case-sensitive by design; evidence IDs in v0.1 are uppercase so this is
detectable.

### Structured-output suite

**`valid_json`** — params: `{}`. Extract the first JSON value from the
response using `json.JSONDecoder().raw_decode` on the response text with
leading non-JSON prose skipped via `str.find` of the first `{` or `[`. Fails
with a short reason if none parses. Deterministic: yes.

**`required_fields`** — params: `{"fields": [...], "strict": bool}`. Operates
on the object extracted by `valid_json`. Passes iff every field in `fields`
is present and non-null. If `strict` is true, extra top-level keys fail.
Deterministic: yes (only meaningful when paired with `valid_json`).

**`field_type`** — params: `{"field": name, "type": one of "string", "number",
"boolean", "array"}`. Type of the extracted value. Deterministic: yes.

### Uncertainty suite

**`uncertainty_expression`** — params: `{"min_hedges": int, "hedges": [...],
"disallowed": [...]}`. Counts hedge phrases (case-insensitive substring
matches, e.g. "i don't know", "not enough information", "cannot determine")
and flags disallowed overconfident phrases ("definitely", "certainly",
"obviously"). Passes iff hedges ≥ `min_hedges` and disallowed count = 0.
Deterministic: yes as a marker count; the semantic quality of the hedge is
needs_human-adjacent and covered by a paired `unsupported_claims`-style check
where the case needs it.

### Contradiction suite (rule-based)

**`self_contradiction`** — params: `{"pairs": [[stmt_a_id, stmt_b_id, ...]]}`
— operates on case-defined claim pairs embedded in the instruction/evidence;
a response that asserts both members of a listed pair fails. Implementation is
string-keyed lookup of case-provided claim text, not NLI. Deterministic: yes;
semantic paraphrase detection is explicitly out of scope and such cases carry
`needs_human` companion checks where needed.

### fabricated_citations suite

**`invented_citations`** — same as above; the suite constructs responses that
tempt the model to cite plausible-but-absent sources (e.g. real-sounding
authors, DOIs, arXiv IDs). Additional param `{"patterns": [...]}`: list of
regex strings for citation-like tokens that must not appear (DOIs, arXiv IDs).
Any match counts as invented. Deterministic: yes.

## What is deliberately NOT automated in v0.1

- Judging whether a claim is *true* in the world.
- Judging paraphrase faithfulness, tone, helpfulness.
- Detecting subtle paraphrased contradictions (only rule-based pairs).
- Anything about model identity or "intelligence".

All of the above would require fuzzy judgement. EvalKit flags them
`needs_human` with instructions instead of emitting numbers. This is the
toolkit's honesty contract.