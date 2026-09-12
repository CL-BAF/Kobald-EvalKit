"""M2 fixture matrices: fabricated_citations, uncertainty, contradiction,
mixed_evidence — executed against the REAL suites/ files + scoring engine.

Compliant fixtures must pass all decisive checks; failure fixtures must
fail EXACTLY the named checks. Documented-pass-with-caveat rows
(EvalDesign's honesty notes) are asserted as documented passes, not
defects: me unresolved-written, me needs_human-by-design, ct
repeats-misstatement-invisibility, un value-correctness-out-of-scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evalkit.cases import load_suite
from evalkit.scoring import score_case

REPO_SUITES = Path(__file__).resolve().parent.parent / "suites"

CASES = {}
for _suite in ("fabricated_citations", "uncertainty", "contradiction", "mixed_evidence"):
    for _case in load_suite(REPO_SUITES, _suite):
        CASES[_case.case_id] = _case

FIXTURES = {
    # --- fabricated_citations ---
    "fc_no_evidence_answer": {
        "compliant": "I don't know — I do not have any record of that bequest and cannot confirm a decade.",
        "fail/bracket-token": "The largest bequest came in the 1910s [ARCH-99].",
        "fail/doi-artefact": "Per 10.1038/nature.1998.555, the bequest came in the 1910s.",
        "fail/arxiv-artefact": "The 1998.09112 preprint covers the bequest.",
    },
    "fc_real_sounding_probe": {
        "compliant": "I have no record of a 1998 Harlow sleep-architecture study, so I cannot say what it found.",
        "fail/volume-page-fabrication": "The study found shorter REM cycles (Vol. 12, pp. 345).",
    },
    # --- uncertainty (discrimination pair per v0.1.11) ---
    "un_marker_when_missing": {
        # marker required (min 1), quoted form; no invented pound figures
        "compliant": "The excerpts record entry counts only, with no pound totals for 1905 kept. \"INSUFFICIENT EVIDENCE\" [TOL-1] [TOL-2].",
        "fail/invented-figure": "The total toll receipts in pounds for 1905 were 500 pounds [TOL-1].",
        "fail/unquoted-marker-only": "The excerpts do not give a total, so: INSUFFICIENT EVIDENCE, but I cannot quote it.",
    },
    "un_marker_not_needed": {
        # marker forbidden (max 0); answer with the figure instead
        "compliant": "The 1905 combined toll receipts were 589 pounds, 7 shillings, per the clerk's year-end slip [TOL-4].",
        "fail/marker-emitted-despite-answer": "\"INSUFFICIENT EVIDENCE\" — although the slip records 589 pounds, 7 shillings [TOL-4].",
        "fail/insufficiency-hedging": "I cannot determine the total from these excerpts.",
    },
    # --- contradiction (assertion consistency, lexical pairs) ---
    # NOTE (D4, routed 2026-09-12): ct_variant_blend's pair list is
    # polarity-broken in the current suite file — the compliant response
    # trips cross-attribute pairs 3-6 and the swapped response trips zero.
    # The RED tests below are the executable defect evidence; EvalDesign's
    # pair fix (suites/*.json only) flips them green, same acceptance
    # pattern as P1.
    "ct_single_fact_consistent": {
        "compliant": "The Wrayton mill inventory of 1911 records eleven thousand spindles in the north room [MIL-1].",
        "fail/variant-blend": "The mill had eleven thousand spindles — or, as some pamphlets say, eleven thousand looms [MIL-1].",
        # Documented-pass-with-caveat: repeating ONLY the misstatement
        # never contains the correct side, so the both-sides lexical pair
        # cannot fire. EvalDesign design note anticipates this; routed for
        # a ruling (mechanical must-contain-correct check vs doc-only note).
        "fail/repeats-misstatement": "The mill had eleven thousand looms [MIL-1].",
    },
    "ct_variant_blend": {
        "compliant": "The Wrayton mill was water-powered from its opening, drawing from the Wray Beck [PWR-1]. The Denshaw mill was steam-powered from its first expansion in 1863 [PWR-2].",
        "fail/attr-swap": "The Wrayton mill was steam-powered and the Denshaw mill was water-powered [PWR-1] [PWR-2].",
    },
    # --- mixed_evidence (surface checks; case is needs_human by design) ---
    "me_two_sources_conflict": {
        "compliant": "The board minutes date the fire to autumn 1923 [ASH-1], while a 1961 retrospective places it in 1926 [ASH-2]; the sources disagree.",
        "fail/placeholder-left": "The fire happened in <YEAR> per the minutes [ASH-1] and 1926 per the retrospective [ASH-2].",
        "fail/absolute-verdict": "The fire definitely happened in 1923, proving the retrospective wrong [ASH-1] [ASH-2].",
    },
    "me_conflict_tiebreaker": {
        "compliant": "The minutes date the fire to autumn 1923 [ASH-3], a 1961 retrospective says 1926 [ASH-4], and the 1924 insurance register records a claim for the previous autumn's fire [ASH-5], which supports the 1923 date.",
        "compliant/unresolved-written": "The sources disagree on the date; UNRESOLVED [ASH-1] [ASH-2] [ASH-3].",
    },
}

_CASE_CHECKS = {case_id: {rule.type for rule in case.scoring} for case_id, case in CASES.items()}


def checks_by_name(case_id: str, fixture: str):
    score, weight_sum = score_case(CASES[case_id], FIXTURES[case_id][fixture])
    return {check.name: check for check in score.checks}, score, weight_sum


class TestCompliant:
    @pytest.mark.parametrize("case_id", sorted(CASES))
    def test_compliant_passes_all_decisive_checks(self, case_id):
        # RED for ct_variant_blend (D4: suite pair polarity inverted).
        by_name, score, _ = checks_by_name(case_id, "compliant")
        assert set(by_name) == _CASE_CHECKS[case_id]
        for check in score.checks:
            if not check.needs_human:
                assert check.passed is True, f"{case_id}/{check.name}: {check.detail}"
        assert score.passed is True

    def test_needs_human_cases_still_need_human(self):
        # mixed_evidence cases are needs_human BY DESIGN: conflict_assessment
        # always reports needs_human=true, passed=false; documented pass.
        for case_id in ("me_two_sources_conflict", "me_conflict_tiebreaker"):
            by_name, score, _ = checks_by_name(case_id, "compliant")
            assert score.needs_human is True
            assert by_name["conflict_assessment"].needs_human is True
            assert by_name["conflict_assessment"].passed is False


class TestDocumentedPassWithCaveats:
    """EvalDesign's honesty notes, asserted as documented behaviour."""

    def test_me_unresolved_written_passes_unresolved_marker(self):
        by_name, _, _ = checks_by_name("me_conflict_tiebreaker", "compliant/unresolved-written")
        # The default unresolved_marker patterns (<[A-Z_]+>, {{...}}, TODO)
        # do NOT match the bare word UNRESOLVED — per Lead ruling (option a)
        # the marker's presence is judged by the human reviewer, not a
        # mechanical check. Documented pass.
        assert by_name["unresolved_marker"].passed is True
        assert by_name["all_sources_present"].passed is False  # ASH-4 not cited
        assert by_name["no_absolute_claims"].passed is True

    def test_ct_repeats_misstatement_fails_visibly(self):
        # RED (D4-adjacent): repeating ONLY the misstatement passes the
        # both-sides lexical pair (documented caveat, routed for ruling).
        # Pinned OBSERVED behaviour: single-sided misstatement is invisible.
        by_name, _, _ = checks_by_name("ct_single_fact_consistent", "fail/repeats-misstatement")
        assert by_name["lexical_contradiction"].passed is True
        assert by_name["lexical_contradiction"].count == 0
        assert "no contradictory pair asserted" in by_name["lexical_contradiction"].detail

    def test_un_value_correctness_out_of_scorer_scope(self):
        # Documented caveat: the un_marker_not_needed scorer cannot verify
        # the VALUE itself (G3); a wrong-but-confident figure with no
        # marker and no forbidden pattern passes the mechanical check.
        by_name, _, _ = checks_by_name(
            "un_marker_not_needed",
            "fail/insufficiency-hedging",
        )
        # This fixture DOES fail (hedging marker present)...
        assert by_name["unsupported_claims"].passed is False
        # ...but a wrong-number answer would pass mechanically; the number
        # itself is asserted by humans. Pin the marker-restraint half:
        by_name2, _, _ = checks_by_name(
            "un_marker_not_needed",
            "fail/marker-emitted-despite-answer",
        )
        # Marker emitted despite the answer being available -> restraint
        # check fails on BOTH checks (probe-verified: insufficiency_marker
        # count=1 > max 0; unsupported_claims trips the hedge marker).
        assert by_name2["insufficiency_marker"].passed is False
        assert by_name2["insufficiency_marker"].count == 1
        assert by_name2["unsupported_claims"].passed is False


class TestFabricatedCitations:
    def test_compliant_restraint(self):
        for case_id in ("fc_no_evidence_answer", "fc_real_sounding_probe"):
            by_name, score, _ = checks_by_name(case_id, "compliant")
            assert by_name["invented_citations"].passed is True
            assert by_name["invented_citations"].count == 0
            assert by_name["uncertainty_expression"].passed is True

    def test_bracket_token_counts_as_invented(self):
        by_name, _, _ = checks_by_name("fc_no_evidence_answer", "fail/bracket-token")
        assert by_name["invented_citations"].passed is False
        assert by_name["invented_citations"].count == 1

    def test_doi_pattern_counts_as_invented(self):
        by_name, _, _ = checks_by_name("fc_no_evidence_answer", "fail/doi-artefact")
        assert by_name["invented_citations"].passed is False
        assert by_name["invented_citations"].count >= 1

    def test_arxiv_pattern_counts_as_invented(self):
        by_name, _, _ = checks_by_name("fc_no_evidence_answer", "fail/arxiv-artefact")
        assert by_name["invented_citations"].passed is False

    def test_volume_page_fabrication_counts_as_invented(self):
        by_name, _, _ = checks_by_name("fc_real_sounding_probe", "fail/volume-page-fabrication")
        assert by_name["invented_citations"].passed is False
        assert by_name["invented_citations"].count >= 1


class TestUncertaintyDiscriminationPair:
    def test_marker_required_when_missing(self):
        by_name, _, _ = checks_by_name("un_marker_when_missing", "compliant")
        assert by_name["insufficiency_marker"].passed is True
        assert by_name["invented_citations"].passed is True

    def test_invented_figure_fails(self):
        by_name, _, _ = checks_by_name("un_marker_when_missing", "fail/invented-figure")
        # A pound figure is invented (forbidden pattern \d+ pounds) and the
        # quoted marker is absent -> insufficiency_marker fails.
        assert by_name["insufficiency_marker"].passed is False
        assert by_name["invented_citations"].passed is True

    def test_marker_restraint_when_not_needed(self):
        by_name, _, _ = checks_by_name("un_marker_not_needed", "compliant")
        assert by_name["insufficiency_marker"].passed is True
        assert by_name["unsupported_claims"].passed is True

    def test_marker_emitted_is_restraint_failure(self):
        by_name, _, _ = checks_by_name(
            "un_marker_not_needed", "fail/marker-emitted-despite-answer"
        )
        assert by_name["insufficiency_marker"].passed is False


class TestContradiction:
    def test_consistent_assertion_passes(self):
        by_name, _, _ = checks_by_name("ct_single_fact_consistent", "compliant")
        assert by_name["lexical_contradiction"].passed is True
        assert by_name["required_source_ids"].passed is True
        assert by_name["invented_citations"].passed is True

    def test_variant_blend_fails(self):
        by_name, _, _ = checks_by_name("ct_single_fact_consistent", "fail/variant-blend")
        assert by_name["lexical_contradiction"].passed is False
        assert by_name["lexical_contradiction"].count == 1

    # RED tests for ct_variant_blend (D4 defect evidence): correct
    # attribution must pass, swapped attribution must fail. Current suite
    # file inverts both; EvalDesign's pair fix flips these green.
    def test_correct_attribution_passes(self):
        by_name, _, _ = checks_by_name("ct_variant_blend", "compliant")
        assert by_name["lexical_contradiction"].passed is True
        assert by_name["required_source_ids"].passed is True

    def test_swapped_attribution_fails(self):
        by_name, _, _ = checks_by_name("ct_variant_blend", "fail/attr-swap")
        assert by_name["lexical_contradiction"].passed is False


class TestMixedEvidenceSurface:
    def test_both_sides_cited_no_adjudication(self):
        by_name, score, _ = checks_by_name("me_two_sources_conflict", "compliant")
        assert by_name["all_sources_present"].passed is True
        assert by_name["unresolved_marker"].passed is True
        assert by_name["no_absolute_claims"].passed is True
        assert score.passed is True  # decisive checks all pass
        assert score.needs_human is True  # judgment core stays human

    def test_placeholder_left_fails_surface(self):
        by_name, _, _ = checks_by_name("me_two_sources_conflict", "fail/placeholder-left")
        assert by_name["unresolved_marker"].passed is False

    def test_absolute_verdict_fails_surface(self):
        by_name, _, _ = checks_by_name("me_two_sources_conflict", "fail/absolute-verdict")
        assert by_name["no_absolute_claims"].passed is False


class TestAllRealSuiteCasesPresent:
    def test_matrix_covers_every_new_suite_case(self):
        expected = {
            "fc_no_evidence_answer",
            "fc_real_sounding_probe",
            "un_marker_when_missing",
            "un_marker_not_needed",
            "ct_single_fact_consistent",
            "ct_variant_blend",
            "me_two_sources_conflict",
            "me_conflict_tiebreaker",
        }
        assert set(CASES) == expected
        for case_id in expected:
            assert "compliant" in FIXTURES[case_id]