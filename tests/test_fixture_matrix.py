"""EvalDesign's fixture matrix executed against the real repo suite.

docs/testing-fixtures.md is the normative fixture spec: for each
evidence_grounding case, a compliant response (must pass ALL checks) and
failure-mode fixtures (must fail EXACTLY the named checks). This suite
asserts exact check outcomes — the pass/FAIL/needs_human matrix — using
the REAL case files from suites/ and the real scoring engine.

KNOWN-DEFECT STATE (M1 gate, Lead ruling 2026-09-12): five tests below are
deliberately RED (no xfail marker): they are the executable proof that the
fixture net catches case-content defects. P1 (EvalDesign post-gate fix,
routed via Lead) flips them green by changing suites/*.json ONLY — never
these tests. The gate state "278 passed + 5 RED documented-with-routed-fixes"
is the ACCEPTED M1 gate state; the red list is recorded in the M1 review as
known-defect evidence.

NOTE for future editors: EMPTY evidence lists are LEGAL per
docs/case-schema.md:42 ("may be empty for some suites") and the loader
accepts them (pinned by TestEmptyEvidenceAccepted). Do NOT re-add an
empty-evidence fixture to tests/fixtures/cases/invalid/ — that was a
pre-amendment mistake and would contradict the schema doc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalkit.cases import load_suite
from evalkit.errors import CaseLoadError
from evalkit.scoring import score_case

REPO_SUITES = Path(__file__).resolve().parent.parent / "suites"

# EvalDesign's fixture texts (docs/testing-fixtures.md). Keyed
# (case_id, fixture_name) -> response text.
FIXTURES = {
    "eg_cite_all_sources": {
        "compliant": (
            "Between 1981 and 1994 the banded reedwarbler population of the "
            "Cobble River floodplain first declined and then stabilised. The 1987 survey "
            "recorded 141 breeding pairs, a 12 percent drop from 1981, attributed to late "
            "spring flooding of nesting banks [SRC-1]. Birds raised there abandon nest "
            "sites when reed height falls below 40 centimetres, which follows a single "
            "flood season [SRC-2]. After two flood spillways were installed upstream in "
            "1992, the 1994 census found the population stable at about 130 pairs "
            "[SRC-3]."
        ),
        "missing-citation": (
            "Between 1981 and 1994 the banded reedwarbler population of the "
            "Cobble River floodplain first declined and then stabilised. The 1987 survey "
            "recorded 141 breeding pairs, a 12 percent drop from 1981, attributed to late "
            "spring flooding of nesting banks [SRC-1]. Birds raised there abandon nest "
            "sites when reed height falls below 40 centimetres, which follows a single "
            "flood season [SRC-2]. After two flood spillways were installed upstream in "
            "1992, the 1994 census found the population stable at about 130 pairs."
        ),
        "invented-citation": (
            "Between 1981 and 1994 the banded reedwarbler population of the "
            "Cobble River floodplain first declined and then stabilised. The 1987 survey "
            "recorded 141 breeding pairs, a 12 percent drop from 1981, attributed to late "
            "spring flooding of nesting banks [SRC-1]. Birds raised there abandon nest "
            "sites when reed height falls below 40 centimetres, which follows a single "
            "flood season [SRC-2]. After two flood spillways were installed upstream in "
            "1992, the 1994 census found the population stable at about 130 pairs "
            "[SRC-3] [SRC-4]."
        ),
        "format": (
            "Between 1981 and 1994 the banded reedwarbler population of the "
            "Cobble River floodplain first declined and then stabilised. The 1987 survey "
            "recorded 141 breeding pairs, a 12 percent drop from 1981, attributed to late "
            "spring flooding of nesting banks (SRC-1). Birds raised there abandon nest "
            "sites when reed height falls below 40 centimetres, which follows a single "
            "flood season (SRC-2). After two flood spillways were installed upstream in "
            "1992, the 1994 census found the population stable at about 130 pairs "
            "(SRC-3)."
        ),
    },
    "eg_no_extra_sources": {
        "compliant": (
            "Kettlebridge's first public library opened in 1911, funded "
            "largely by a bequest from local mill owner Harriet Voss [DOC-7]."
        ),
        "distractor-cited": (
            "Kettlebridge's first public library opened in 1911, funded "
            "largely by a bequest from local mill owner Harriet Voss [DOC-7] [DOC-9]."
        ),
        "invented-citation": (
            "Kettlebridge's first public library opened in 1911, funded "
            "largely by a bequest from local mill owner Harriet Voss [DOC-7] [DOC-12]."
        ),
    },
    "eg_flag_insufficiency": {
        "compliant": (
            "The excerpts do not establish which year had the highest "
            "repair cost. Neither ARCH-3 nor ARCH-4 lists any cost amounts, so the "
            "question cannot be determined from the provided excerpts."
        ),
        "hallucinated-answer": (
            "Water-damage repairs cost the town the most in 1968, when flooding "
            "damaged the archive repository."
        ),
        "verbose-uncited": (
            "It is difficult to determine which year had the highest repair cost "
            "from the material provided. The excerpts do not establish the answer, "
            "since neither document records actual cost figures for any year. "
            "Without amounts to compare, the question cannot be determined "
            "from the excerpts alone, and any specific year would be invented "
            "rather than grounded in the provided material."
        ),
    },
    "eg_summarize_grounded": {
        "compliant": (
            "The Larkspur Valley Observatory recorded 41 days of measurable "
            "rainfall in 1971, the lowest in its records to that point [OBS-1]. By 1976 "
            "the count was 63 days, with two November storms contributing nearly a third "
            "of the annual total [OBS-2]."
        ),
        "unclaimed-addition": (
            "The Larkspur Valley Observatory recorded 41 days of measurable "
            "rainfall in 1971, the lowest in its records to that point [OBS-1]. By 1976 "
            "the count was 63 days, with two November storms contributing nearly a third "
            "of the annual total [OBS-2]. Rainfall across the region "
            "recovered steadily throughout the late 1970s."
        ),
        "invented-citation": (
            "The Larkspur Valley Observatory recorded 41 days of measurable "
            "rainfall in 1971, the lowest in its records to that point [OBS-1]. By 1976 "
            "the count was 63 days, with two November storms contributing nearly a third "
            "of the annual total [OBS-2] [OBS-4]."
        ),
    },
    "eg_citation_format_strict": {
        "compliant": (
            "In 1923 the Fenwick Ferry Company operated four daily "
            "crossings from Kettlebridge to Nether Fen [DOC-4]. In 1926 the service was "
            "reduced to two daily crossings during winter months because of fog delays at "
            "the Nether Fen landing [DOC-5]."
        ),
        "prose-citation": (
            "In 1923 the Fenwick Ferry Company operated four daily "
            "crossings from Kettlebridge to Nether Fen (DOC-4). In 1926 the service was "
            "reduced to two daily crossings during winter months because of fog delays at "
            "the Nether Fen landing (DOC-5)."
        ),
        "lowercase-id": (
            "In 1923 the Fenwick Ferry Company operated four daily "
            "crossings from Kettlebridge to Nether Fen [doc-4]. In 1926 the service was "
            "reduced to two daily crossings during winter months because of fog delays at "
            "the Nether Fen landing [doc-5]."
        ),
    },
}

_CASE_CACHE: dict = {}


def get_case(case_id: str):
    if not _CASE_CACHE:
        cases = load_suite(REPO_SUITES, "evidence_grounding")
        for case in cases:
            _CASE_CACHE[case.case_id] = case
    return _CASE_CACHE[case_id]


def checks_by_name(case_id: str, fixture: str):
    case = get_case(case_id)
    score, weight_sum = score_case(case, FIXTURES[case_id][fixture])
    return {check.name: check for check in score.checks}, score, weight_sum


CASE_CHECKS = {
    "eg_cite_all_sources": {"required_source_ids", "invented_citations"},
    "eg_no_extra_sources": {"required_source_ids", "invented_citations"},
    "eg_flag_insufficiency": {"unsupported_claims", "invented_citations"},
    "eg_summarize_grounded": {"unsupported_claims", "invented_citations", "required_source_ids"},
    "eg_citation_format_strict": {"required_source_ids", "invented_citations"},
}


class TestCompliantFixturesPassEverything:
    @pytest.mark.parametrize(
        "case_id",
        sorted(FIXTURES),
    )
    def test_compliant_passes_all_checks(self, case_id):
        # RED for eg_flag_insufficiency (known case defect, P1 in flight).
        by_name, score, _ = checks_by_name(case_id, "compliant")
        assert set(by_name) == CASE_CHECKS[case_id]
        for check in score.checks:
            assert check.passed is True, f"{case_id}/{check.name}: {check.detail}"
        assert score.needs_human is False
        assert score.passed is True


class TestEgCiteAllSources:
    def test_missing_citation_fails_only_required(self):
        by_name, _, _ = checks_by_name("eg_cite_all_sources", "missing-citation")
        assert by_name["required_source_ids"].passed is False
        assert by_name["required_source_ids"].count == 1
        assert "SRC-3" in by_name["required_source_ids"].detail
        assert by_name["invented_citations"].passed is True

    def test_invented_citation_fails_only_invented(self):
        by_name, _, _ = checks_by_name("eg_cite_all_sources", "invented-citation")
        assert by_name["required_source_ids"].passed is True
        assert by_name["invented_citations"].passed is False
        assert by_name["invented_citations"].count == 1
        assert "'SRC-4'" in by_name["invented_citations"].detail

    def test_prose_format_fails_required_zero_invented(self):
        by_name, _, _ = checks_by_name("eg_cite_all_sources", "format")
        assert by_name["required_source_ids"].passed is False
        # Zero tokens found: invented count stays 0 (honest format failure).
        assert by_name["invented_citations"].passed is True
        assert by_name["invented_citations"].count == 0
        assert by_name["required_source_ids"].count == 3


class TestEgNoExtraSources:
    # RED (known case defect D3, P1 in flight): eg_no_extra_sources'
    # invented_citations ids ['DOC-7'] treats legitimate evidence DOC-9
    # as invented. EvalDesign fix routed via Lead 2026-09-12.
    def test_distractor_cited_fails_required_only(self):
        by_name, _, _ = checks_by_name("eg_no_extra_sources", "distractor-cited")
        assert by_name["required_source_ids"].passed is False
        assert by_name["invented_citations"].passed is True
        # DOC-9 is legitimate evidence, so invented count is 0.
        assert by_name["invented_citations"].count == 0

    def test_invented_citation_fails_only_invented(self):
        by_name, _, _ = checks_by_name("eg_no_extra_sources", "invented-citation")
        assert by_name["required_source_ids"].passed is True
        assert by_name["invented_citations"].passed is False
        assert by_name["invented_citations"].count == 1


class TestEgFlagInsufficiency:
    # RED tests below (known case defect: marker polarity inverted —
    # compliance phrases declared as FAILURE markers; EvalDesign P1
    # re-declaration routed via Lead 2026-09-12 flips them green).
    def test_compliant_flags_insufficiency_and_passes(self):
        by_name, score, _ = checks_by_name("eg_flag_insufficiency", "compliant")
        assert by_name["unsupported_claims"].passed is True
        assert by_name["unsupported_claims"].needs_human is False
        assert by_name["invented_citations"].passed is True

    def test_hallucinated_answer_is_plain_fail_not_needs_human(self):
        by_name, _, _ = checks_by_name("eg_flag_insufficiency", "hallucinated-answer")
        check = by_name["unsupported_claims"]
        assert check.passed is False
        assert check.needs_human is False
        assert by_name["invented_citations"].passed is True

    def test_verbose_uncited_triggers_needs_human_rule(self):
        # EvalDesign: push hardest here — zero tokens + >= 200 chars.
        by_name, score, _ = checks_by_name("eg_flag_insufficiency", "verbose-uncited")
        check = by_name["unsupported_claims"]
        assert check.needs_human is True
        assert check.passed is False
        assert check.count is None
        assert score.needs_human is True
        assert score.passed is True  # decisive checks all pass
        assert by_name["invented_citations"].passed is True


class TestEgSummarizeGrounded:
    def test_compliant_passes_all_three(self):
        by_name, _, _ = checks_by_name("eg_summarize_grounded", "compliant")
        assert by_name["unsupported_claims"].passed is True
        assert by_name["invented_citations"].passed is True
        assert by_name["required_source_ids"].passed is True

    # RED (known case defect: attribution-phrase markers don't catch the
    # failure mode; EvalDesign P1 re-declaration flips this green).
    def test_unclaimed_addition_fails_only_unsupported(self):
        by_name, _, _ = checks_by_name("eg_summarize_grounded", "unclaimed-addition")
        assert by_name["required_source_ids"].passed is True
        assert by_name["invented_citations"].passed is True
        check = by_name["unsupported_claims"]
        assert check.passed is False
        assert check.count == 2  # two attribution markers tripped
        assert "'according to'" in check.detail or "x1" in check.detail

    def test_invented_citation_fails_only_invented(self):
        by_name, _, _ = checks_by_name("eg_summarize_grounded", "invented-citation")
        assert by_name["required_source_ids"].passed is True
        assert by_name["invented_citations"].passed is False
        assert by_name["invented_citations"].count == 1


class TestEgCitationFormatStrict:
    def test_prose_citation_fails_required_only(self):
        by_name, _, _ = checks_by_name("eg_citation_format_strict", "prose-citation")
        assert by_name["required_source_ids"].passed is False
        assert by_name["required_source_ids"].count == 2
        assert by_name["invented_citations"].passed is True
        assert by_name["invented_citations"].count == 0

    def test_lowercase_id_fails_required_only(self):
        by_name, _, _ = checks_by_name("eg_citation_format_strict", "lowercase-id")
        assert by_name["required_source_ids"].passed is False
        assert by_name["required_source_ids"].count == 2
        assert by_name["invented_citations"].passed is True
        assert by_name["invented_citations"].count == 0


class TestFixtureMatrixIntegrity:
    def test_every_case_has_compliant_fixture(self):
        for case_id, fixtures in FIXTURES.items():
            assert "compliant" in fixtures, case_id

    def test_all_fixture_texts_are_nonempty_strings(self):
        for case_id, fixtures in FIXTURES.items():
            for name, text in fixtures.items():
                assert isinstance(text, str) and text.strip(), f"{case_id}/{name}"

    def test_real_suite_loads_for_matrix(self):
        cases = load_suite(REPO_SUITES, "evidence_grounding")
        assert {c.case_id for c in cases} == set(FIXTURES)


class TestEmptyEvidenceAccepted:
    def test_loader_accepts_empty_evidence_list(self, tmp_path):
        # Positive contract pin: docs/case-schema.md:42 permits empty
        # evidence ("may be empty for some suites") and the loader must
        # accept it. Do NOT re-add an empty-evidence rejection fixture —
        # see module docstring note.
        import json

        suite_dir = tmp_path / "evidence_grounding"
        suite_dir.mkdir()
        payload = {
            "schema_version": "1",
            "case_id": "no_evidence_probe",
            "suite": "evidence_grounding",
            "title": "Empty evidence is legal",
            "purpose": "Pins loader acceptance of an empty evidence list per schema.",
            "evidence": [],
            "instruction": "Answer from your own knowledge.",
            "constraints": "Doc-only.",
            "scoring": [{"type": "valid_json", "params": {}}],
            "expected": "Doc-only.",
        }
        (suite_dir / "no_evidence_probe.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        cases = load_suite(tmp_path, "evidence_grounding")
        assert len(cases) == 1
        assert cases[0].evidence == []
        assert cases[0].evidence_ids == []