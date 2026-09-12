# Mock-Provider Test Fixtures — evidence_grounding (M1)

Status: proposal by EvalDesign for Tests (accepted by Lead as R2). Updated in
the P1 batch (post-v0.1.0-tag): marker polarity fixes (D1/D2) and the D3 ids
fix are reflected here — this doc, the case files, and Tests'
`test_fixture_matrix.py` now agree. Each fixture is a canned `MockProvider`
response keyed to a case. "Compliant" must pass all the case's checks; each
failure-mode fixture must fail EXACTLY the named check(s) and pass everything
else, so tests can assert scorer precision. All strings are invented content —
same fictional universe as the suite files, redistributable under MIT.

Usage note: fixtures are response TEXT only; `MockProvider` returns them
verbatim. If the runner wraps prompts, fixtures stay valid because checks run
on the response text only.

## eg_cite_all_sources

- `compliant`: "Between 1981 and 1994 the banded reedwarbler population of the
  Cobble River floodplain first declined and then stabilised. The 1987 survey
  recorded 141 breeding pairs, a 12 percent drop from 1981, attributed to late
  spring flooding of nesting banks [SRC-1]. Birds raised there abandon nest
  sites when reed height falls below 40 centimetres, which follows a single
  flood season [SRC-2]. After two flood spillways were installed upstream in
  1992, the 1994 census found the population stable at about 130 pairs
  [SRC-3]."
- `fail/missing-citation` (fails required_source_ids only): same text but the
  final sentence drops "[SRC-3]"; SRC-2 and SRC-1 remain.
- `fail/invented-citation` (fails invented_citations only): compliant text but
  "[SRC-4]" appended after "[SRC-3]" in the last sentence.
- `fail/format` (fails required_source_ids AND invented_citations stays 0 but
  visible): same text with citations written as "(SRC-1)", "(SRC-2)",
  "(SRC-3)" — zero tokens found; detail must state format failure.

## eg_no_extra_sources

- `compliant`: "Kettlebridge's first public library opened in 1911, funded
  largely by a bequest from local mill owner Harriet Voss [DOC-7]."
- `fail/distractor-cited` (fails required_source_ids via allow_extras=false;
  after the D3 ids fix it does NOT trip invented_citations — DOC-9 is
  legitimate evidence): same sentence but citing "[DOC-7] [DOC-9]" (DOC-9 is
  the Alder Street planning note, a distractor).
- `fail/invented-citation` (fails invented_citations only): compliant text
  with an extra "[DOC-12]" (not among provided evidence).

## eg_flag_insufficiency

- `compliant`: "The excerpts do not establish which year had the highest
  repair cost. Neither ARCH-3 nor ARCH-4 lists any cost amounts, so the
  question cannot be determined from the provided excerpts." (Contains none of
  the declared FAILURE markers.)
- `fail/hallucinated-answer` (fails unsupported_claims): "Water-damage repairs
  cost the town the most in 1968, when flooding damaged the archive
  repository." (Trips 'cost the most in' and 'repairs cost'; no citation —
  zero tokens + length < 200 keeps this a plain fail, not needs_human.)
- `needs_human/verbose-uncited` (triggers unsupported_claims needs_human rule):
  a 220+ char uncited response that hedges ("It is difficult to determine…
  the excerpts do not establish…") but mentions no citation token; expect
  status needs_human, passed=false, needs_human=true.

## eg_summarize_grounded

- `compliant`: "The Larkspur Valley Observatory recorded 41 days of measurable
  rainfall in 1971, the lowest in its records to that point [OBS-1]. By 1976
  the count was 63 days, with two November storms contributing nearly a third
  of the annual total [OBS-2]."
- `fail/unclaimed-addition` (fails unsupported_claims, count 2 > max 1):
  compliant text plus an uncited sentence: "Rainfall across the region
  recovered steadily throughout the late 1970s." (trips the declared FAILURE
  markers 'rainfall across the region' and 'recovered steadily'; no token, no
  other check affected.)
- `fail/invented-citation` (fails invented_citations only): compliant text
  with "[OBS-4]" appended to the second sentence.

## eg_citation_format_strict

- `compliant`: "In 1923 the Fenwick Ferry Company operated four daily
  crossings from Kettlebridge to Nether Fen [DOC-4]. In 1926 the service was
  reduced to two daily crossings during winter months because of fog delays at
  the Nether Fen landing [DOC-5]."
- `fail/prose-citation` (fails required_source_ids; invented stays 0): same
  text, citations replaced with "(DOC-4)" and "(DOC-5)".
- `fail/lowercase-id` (fails required_source_ids; invented stays 0): same text
  with "[doc-4]" and "[doc-5]" (case-sensitivity is by design).

## Expected outcomes matrix (for test asserts)

Polarity note (P1): `unsupported_claims` markers are FAILURE markers —
phrases a bad response contains. The compliant fixtures below provably avoid
every declared marker.

| fixture | required_source_ids | invented_citations | unsupported_claims |
|---|---|---|---|
| eg_cite_all_sources compliant | pass | pass (0) | n/a |
| … missing-citation | FAIL | pass | n/a |
| … invented-citation | pass | FAIL (1>0) | n/a |
| … format | FAIL | pass (0) | n/a |
| eg_no_extra_sources compliant | pass | pass | n/a |
| … distractor-cited | FAIL | pass (0; DOC-9 is legitimate evidence after the D3 ids fix) | n/a |
| … invented-citation | pass | FAIL ([DOC-12] is non-evidence) | n/a |
| eg_flag_insufficiency compliant | n/a | pass | pass (0 markers) |
| … hallucinated-answer | n/a | pass | FAIL ('cost the most in' trips; plain fail, not needs_human) |
| … verbose-uncited | n/a | pass | needs_human=true, passed=false |
| eg_summarize_grounded compliant | pass | pass | pass (0 ≤ 1) |
| … unclaimed-addition | pass | pass | FAIL (2>1: 'rainfall across the region', 'recovered steadily') |
| … invented-citation | pass | FAIL | pass |
| eg_citation_format_strict compliant | pass | pass | n/a |
| … prose-citation | FAIL | pass (0) | n/a |
| … lowercase-id | FAIL | pass (0) | n/a |

n/a = check not present in that case. Every FAIL row must fail ONLY the
column(s) marked FAIL and keep `count`/`detail` consistent with the matrix so
Tests can assert exact check outcomes, not just booleans. Verified: the full
22-test fixture matrix (`tests/test_fixture_matrix.py`) is green against the
P1-updated case files.