# Scoring Rules v0.1 — How EvalKit Scores

Status: owned by EvalDesign, ratified through contract Amendments
v0.1.1-v0.1.10. Normative for scorer implementations in `evalkit/scoring/*`
(Core) and for the aggregate formulas used by `run` / `report` / `compare`
(Core). Tests verifies implementations against this spec. Where this doc and
the implementation disagree, the discrepancy is a finding — v0.1 code is the
reference implementation (Lead's rule), and this doc is kept in lockstep with
it.

## Two kinds of checks

**Deterministic checks** compute a definite pass/fail from the response text
and case parameters. Same response + same case ⇒ same result, forever. Counts
and limits appear in `check.detail` so a human can verify the arithmetic.

**needs_human checks** cover judgement we refuse to fake (e.g. "is this
paraphrase actually faithful to the evidence?"). They are emitted with
`passed = false`, `needs_human = true`, and a detail explaining what a human
should look at. They never tip a case to passed or failed on their own and are
excluded from aggregates (Amendment v0.1.7 #1).

## Frozen semantics (Amendments v0.1.2 #4, v0.1.3, v0.1.7)

- A check has `name: str`, `passed: bool`, `detail: str`,
  `count: int | None`, `needs_human: bool` (default false).
- `ScoreResult.passed` = every non-`needs_human` check passed.
- `ScoreResult.needs_human` = true iff any check is `needs_human`.
- `CaseResult.passed` = `ScoreResult.passed` AND NOT `ScoreResult.needs_human`.
- `CaseResult.status` is exactly one of `"passed" | "failed" | "needs_human" |
  "error"` (Amendment v0.1.4 #2: no "skipped" in v0.1).
- `weight` (float, default 1.0) affects **reported aggregates only**, never
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
  sample of any population; (3) rates from different models, quantisations or
  option sets are not comparable unless the user controls those variables
  (compare must verify config comparability, Amendment v0.1.3 #1); (4) latency
  is recorded but never aggregated into any score, and docs never publish
  sub-millisecond latency claims (Amendments v0.1.4 #1, v0.1.5); (5)
  needs_human-heavy results are BY-DESIGN exclusions from
  `weighted_pass_rate`, not missing data — a suite whose cases are mostly
  human-judgement probes will show a low case count in the aggregate and a
  large needs_human list, and that is the honest reading (F-B).
- Display rule (F-D, pinned): a suite with ZERO scoreable cases reports that
  fact in reports ("no scoreable cases — all need human review"); it must
  never display as 0% and never as NaN. `compare` inherits this rule; it must
  not improvise a number.
- No overall "score" number is published. Reports show pass/fail counts, the
  weighted pass rate, needs_human counts, and per-check details.

## Citation token format (normative for extractors)

A citation token is `[` + one or more uppercase letters, digits, or hyphens,
length 2-24, `]` — e.g. `[SRC-01]`, `[DOC-7]`, `[GEO-2]`. Regex:
`\[[A-Z0-9][A-Z0-9-]{1,23}\]`. Evidence IDs use the same charset, so the
loader can reject an evidence ID that can never be matched as a token. Tokens
are extracted from the raw response text.

Two caveats, always stated in reports: (1) a model that cites as "(SRC-01)"
or "Source 1" produces no tokens — the check fails visibly and the detail says
so (an honest format failure, not a silent zero); (2) IDs are case-sensitive
by design; evidence IDs in v0.1 are uppercase so this is detectable.

## Registered scorer types (v0.1)

Params below are normative. `expected`/`constraints` in a case are never read
by scorers. Unknown scoring types are rejected by the loader.

Scorer-surface discipline (G3, agreed): no `value_equals` scorer in v0.1 —
content-correctness of extracted VALUES is a human-review concern or a future
amendment; the scorer surface stays minimal.

### evidence_grounding suite

**`required_source_ids`** — params: `{"ids": [...], "allow_extras": bool}`.
Citation tokens are extracted from the response. Check passes iff every ID in
`ids` appears at least once and, if `allow_extras` is false, no other ID from
the case's `evidence` appears. Non-evidence tokens do not fail this check;
they are counted by `invented_citations`. Deterministic: yes.

**`invented_citations`** — params: `{"max_allowed": int, "ids": [...]}`.
Counts citation tokens in the response that are not in `ids` (the case's
legitimate evidence IDs). Passes iff invented count ≤ `max_allowed`.
Deterministic: yes (regex counting).

**Note (F-A):** ANY bracketed uppercase token matching the citation-token
regex that is not in the evidence ID set counts as invented — including
real-world acronym-like tokens (e.g. `[IEEE-754]` in a technical answer fails
`max_allowed = 0`). Case authors must write evidence to avoid acronym
collisions (do not name evidence IDs after common standards/acronyms) and
should prefer instructions that say "cite ONLY with the provided IDs".

**`unsupported_claims`** — params: `{"max_allowed": int, "markers": [...],
"min_length": int (default 200)}`. Deterministic *marker* scoring, not
semantic scoring. Pinned algorithm (Amendment v0.1.10; matches
`evalkit/scoring/grounding.py`): count occurrences of the case's declared
failure markers — case-insensitive substring search; overlapping occurrences
of the same marker each count; multiple occurrences within one sentence each
count. Passes iff total count ≤ `max_allowed`.

Marker matching is PLAIN SUBSTRING SEARCH with a known false-positive class:
negations of a marker still count, and markers matching inside innocuous
constructions still count. Case-author guidance: choose markers unlikely to
appear innocently (test your markers against the compliant fixture text).
Any response tripping a marker fails VISIBLY and the check detail NAMES the
markers (e.g. `'I think' x2 (max allowed 0)`) — the explainability promise;
the implementation must include the marker text in the detail (routed to
Core).

needs_human rule (unchanged): if the response contains ZERO citation tokens
but its length ≥ `min_length` (default 200), this check emits
`needs_human = true` (nothing was verifiable mechanically).

Design history (considered and rejected): a sentence-split algorithm
(split on `[.!?]\s+`, ≥ 8 alphabetic words, no token, no hedge prefix) was
the draft v0.1 design; it was superseded by the marker-count algorithm above
because sentence splitting is a worse heuristic than an explicit,
case-declared marker list.

### structured_output suite

**`valid_json`** — params: `{}`. Pinned extraction (matches
`evalkit/scoring/rules.py::_extract_first_json`): the scorer takes the
earlier of the first `{` and the first `[` by POSITION (i.e. the first
JSON-looking opener in the text, `{` then `[` ties broken by position), and
`json.JSONDecoder().raw_decode` runs from that index ONLY. If it fails, the
check FAILS — the other opener is NOT tried. Rationale: try-each-position
creates hidden leniency toward malformed-prefix responses; first-position
matches "the model emits exactly one JSON document" instruction conventions.
Deterministic: yes.

**`required_fields`** — params: `{"fields": [...], "strict": bool}` (matches
`evalkit/scoring/rules.py`). Operates on the value extracted by the same
first-position logic as `valid_json`. Passes iff every field in `fields` is
present and non-null in the extracted OBJECT. If the extracted value is not
an object, the check fails with the actual type named. If `strict` is true,
extra top-level keys fail.

ARRAY SEMANTICS (pinned, G1): when the extracted value is an array,
`required_fields` applies to EVERY ELEMENT — passes iff all elements contain
the required fields; `count` = number of violating elements; the detail names
the first offenders. STRICT IS PER-ELEMENT (pinned): when strict is true,
each element must ALSO contain no extra keys — an element violating either
the required-fields rule or the strict-extras rule counts as a violating
element. (v0.1 implementation note: Core implements this per the updated
doc when the M1 gate clears; until then the landed behavior is "array-
extracted value fails with type named". Tests bind to whichever the gate
review confirms is current.) Deterministic: yes.

**`field_type`** — params: `{"field": name, "type": one of "string",
"number", "boolean", "array", "object"}`. Type of the named field in the
extracted object; `number` excludes booleans; the named field must exist.
ROOT-CHECK CONVENTION (pinned, G2): `{"field": "$", "type": ...}` denotes the
ROOT extracted value — `field_type` with `field: "$"` checks the type of the
entire extracted value (e.g. an array root). Deterministic: yes.

### uncertainty suite (marker convention — Amendment: Lead design constraint)

Deterministic scoring is only honest here via an explicit marker convention.
The case `instruction` must require an EXACT marker token (e.g.
`INSUFFICIENT EVIDENCE`) when the evidence does not contain the answer.
Params: `{"marker": string, "min_marker_count": int (default 1),
"forbidden_patterns": [...], "marker_in_quotes": bool (default true)}`.

`marker_in_quotes` (pinned): when true, the scorer searches for the marker
string exactly as it appears between the quotes in the instruction, INCLUDING
the quote characters themselves (i.e. the literal `"INSUFFICIENT EVIDENCE"`
with quote chars). When false, the bare marker string is matched.

Scorer `insufficiency_marker`: passes iff the marker string appears at least
`min_marker_count` times (marker_in_quotes: match the quoted form the
instruction demanded, e.g. `"INSUFFICIENT EVIDENCE"`), AND no
`forbidden_patterns` regex (fabricated specifics: invented dates, names,
numbers the case lists as absent-from-evidence) matches, AND the response
does not contain any citation-like token absent from the evidence ID set.

NOTE (v0.1.11 — insufficiency_marker spec PINNED for post-gate
implementation): params `{"marker": str, "min_marker_count": int (default 1),
"max_marker_count": int | None (default None = unbounded),
"forbidden_patterns": [regex...], "marker_in_quotes": bool (default true)}`.
Passes iff marker count (substring search; quoted literal when
marker_in_quotes=true) >= min_marker_count AND (max_marker_count is None OR
count <= max_marker_count) AND no forbidden_pattern matches AND no
citation-like token absent from the evidence ID set appears. needs_human: no.
The max_marker_count upper bound is the NEW capability enabling the
discrimination pair (marker required when evidence lacks the figure; marker
FORBIDDEN when evidence has it). The landed `uncertainty_expression` remains
the registered v0.1 scorer until Core implements this post-gate.

**Stated limitation (must appear in README and suite docs):** lexical marker
compliance is NOT calibrated confidence. A model can emit the marker and still
be poorly calibrated elsewhere; a model may be well-calibrated yet phrase
insufficiency differently and fail. This measures instruction-following under
evidence scarcity, nothing more.

### contradiction suite (rule-based — Lead design constraint)

Deterministic only via engineered lexical traps. Scorer `lexical_contradiction`
(matches `evalkit/scoring/rules.py`): params `{"pairs": [[claim_a, claim_b],
...]}` — each pair is two phrases (case-insensitive substring match) that must
not BOTH appear in the response. Passes iff zero pairs have both members
present; the detail names each violated pair. Implementation is string-keyed
lookup of case-provided claim phrases, not NLI.

Case-author guidance: pick the two phrases so each is distinctive enough that
a faithful answer to only one side cannot contain both (distinct names, dates,
numbers). The v0.1 draft's richer trap shape (probe/disinct_tokens/
min_absent) was simplified to bare pairs in the landed implementation; cases
use pairs only.

**Stated limitation:** rule-based, never semantic understanding. Paraphrased
contradictions without the pinned phrases are invisible to this scorer; cases
needing semantic judgement carry `needs_human` companion checks instead.

### fabricated_citations suite

**`invented_citations`** — same algorithm as above, plus optional param
`{"patterns": [...]}`: list of regex strings for citation-like artefacts that
must not appear (DOIs `10\.\d{4,9}/\S+`, arXiv IDs `\d{4}\.\d{4,5}`,
ISBN-like strings). Any match counts as invented (regex matches count in
addition to non-evidence tokens; pattern hits are named in the detail,
capped at 5 distinct then "and N more"). Deterministic: yes.

### mixed_evidence suite (surface checks only — Lead design constraint)

Full deterministic scoring of "weighs evidence" is NOT honestly achievable
(keyword-bingo risk). v0.1 scope: surface checks only, with the judgment core
flagged for humans. (Matches `evalkit/scoring/rules.py`.)

- `all_sources_present` — params: none (uses the case's evidence IDs): every
  evidence ID is cited as a token at least once. Deterministic: yes.
- `unresolved_marker` — params: `{"patterns": [...]}` (defaults to
  `<[A-Z_]+>`, `{{name}}`, `TODO` when omitted): unresolved placeholder
  patterns must NOT appear (v0.1.10 note: this is the landed meaning —
  placeholder hygiene; the earlier draft meaning "required open-question
  marker must appear" is NOT what the implementation does and cases must not
  rely on it). Deterministic: yes.
- `no_absolute_claims` — params: `{"phrases": [...], "needs_human": bool}`:
  absolute-confidence phrases ("definitely", "certainly", "obviously" by
  default) must not appear; if `needs_human` is true, any hit additionally
  sets the check needs_human. Deterministic: yes.
- Companion check `conflict_assessment` — params: `{"instructions": string}`
  (optional): ALWAYS `needs_human = true`, passed = false, detail =
  instructions (what a human should judge: how the response resolves the
  conflicting evidence). This keeps the case honest: compliance is measured,
  reasoning quality is reviewed by a human. Every mixed_evidence case
  includes this check, so all such cases report `needs_human = true` and are
  excluded from aggregates by design.

**Stated limitation (README, per Lead):** mixed_evidence aggregates measure
instruction compliance and surface hygiene, NOT reasoning quality.

## What is deliberately NOT automated in v0.1

- Judging whether a claim is *true* in the world.
- Judging paraphrase faithfulness, tone, helpfulness.
- Detecting subtle paraphrased contradictions (only rule-based pairs).
- Calibrated-confidence measurement (markers are compliance, not calibration).
- Anything about model identity or "intelligence".

All of the above would require fuzzy judgement. EvalKit flags them
`needs_human` with instructions instead of emitting numbers. This is the
toolkit's honesty contract.

## Implementation constraints for the loader/scorers (normative for Core)

- All case validation and scoring is hand-rolled stdlib validation. The
  `$schema` / `$id` members of `docs/case-schema.json` are inert identifiers:
  the loader MUST NOT fetch, resolve, or process any URL from case files or
  schema files (no network in evaluation, ever).
- Scorers are pure functions of (case, response_text). No randomness, no
  clocks, no environment lookups inside a scorer.