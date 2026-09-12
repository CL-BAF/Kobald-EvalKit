# Suite: evidence_grounding — Design Note (M1)

Status: owned by EvalDesign. Scorer implementations live in `evalkit/scoring/`
(Core implements; Tests verify against this spec).

## What this suite tests

Does the model stay inside the evidence it was given? Three behaviours:

1. **Cite what you used.** The response cites every source ID the instruction
   requires, in the required token format.
2. **Don't invent.** The response does not cite sources that were not provided
   (fabricated IDs, plausible-looking but absent).
3. **Don't assert beyond evidence without flagging it.** Unsupported claims are
   either absent, hedge-marked, or few enough to be explicitly tolerated by the
   case.

## Why (purpose pattern)

Every case answers: "can a local model ground its statements in provided
evidence instead of filling gaps from prior knowledge?" This matters for
RAG-style use where an ungrounded answer is worse than a refusal. Local models
commonly drift to parametric knowledge; these cases make the drift visible and
countable.

## Scoring model (normative)

Each case uses a subset of:

- `required_source_ids` — every listed ID must appear as a citation token;
  `allow_extras` controls whether other provided IDs may also appear.
- `invented_citations` — citation tokens not in the legitimate ID set, ≤
  `max_allowed` (usually 0).
- `unsupported_claims` — heuristic sentence-split; claims without citation
  tokens and without hedge markers, ≤ `max_allowed`. Emits `needs_human` when
  the response contains zero citation tokens but is substantial prose (see
  docs/scoring.md caveats).

Weights are ordinal emphasis only (never affect pass/fail): citing = weight 3,
not inventing = weight 4 (fabrication is the worse failure), claim hygiene =
weight 2.

## Case roster (M1, 5 cases)

| case_id | tests | scoring |
|---|---|---|
| `eg_cite_all_sources` | cite 3 required IDs | required_source_ids (w3), invented_citations (w4) |
| `eg_no_extra_sources` | cite exactly the 1 relevant source, ignore 2 distractors | required_source_ids(allow_extras=false) (w3), invented_citations (w4) |
| `eg_flag_insufficiency` | refuse/flag when evidence does not contain the answer | required_source_ids (w3), unsupported_claims (w2) |
| `eg_summarize_grounded` | summary using only provided evidence | unsupported_claims (w2), invented_citations (w4), required_source_ids (w3) |
| `eg_citation_format_strict` | exact token format `[XX-N]` | required_source_ids (w3), invented_citations (w4) |

Content: invented fictional sources (a fictional ornithology society, a
fictional municipal archive, a fictional weather observatory, etc.). All
redistributable under MIT.

## Known limitations (stated up front)

- Citation-token regex counting rewards *format compliance*, not actual
  grounding. A model could cite the right IDs next to wrong statements. We
  accept this and say so: format-level grounding is what v0.1 measures.
- Sentence-splitting for unsupported-claim counting is heuristic. Thresholds
  are set so only clearly excessive claim-dumping fails; borderline prose
  triggers `needs_human` instead of a fake number.
- Suite results do not transfer to non-English responses; v0.1 is
  English-only (stated in reports).