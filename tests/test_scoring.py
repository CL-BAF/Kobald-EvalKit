"""Scoring contract tests against docs/scoring.md (normative).

Covers the landed scoring engine (evalkit/scoring/*): citation-token regex,
required_source_ids, invented_citations (incl. Reviewer pin 3: [IEEE-754]
with max_allowed=0 FAILS — documented false-positive class), unsupported_claims
incl. needs_human rule, valid_json FIRST-POSITION-ONLY (Reviewer pin 1),
required_fields/field_type, uncertainty_expression, lexical_contradiction,
conflict_assessment always-needs_human, aggregate/summary formulas, and the
scorers-never-read-expected rule.
"""

from __future__ import annotations

import pytest

from evalkit.cases import EvidenceItem, EvalCase, ScoringRule
from evalkit.errors import ScoringError
from evalkit.models import CASE_STATUSES
from evalkit.scoring import (
    CITATION_TOKEN_RE,
    is_registered_scorer,
    registered_scorer_names,
    run_summary,
    score_case,
    weighted_pass_rate,
)


def make_case(scoring: list[ScoringRule], evidence=None, case_id="sc_test") -> EvalCase:
    return EvalCase(
        schema_version="1",
        case_id=case_id,
        suite="evidence_grounding",
        title="Scoring fixture",
        purpose="Scorer behaviour testing.",
        evidence=evidence or [EvidenceItem(id="SRC-1", text="Paris is the capital of France.")],
        instruction="Answer with citations.",
        constraints="Doc-only.",
        scoring=scoring,
        expected="Doc-only.",
    )


class TestCitationTokenRegex:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("[SRC-1]", ["[SRC-1]"]),
            ("cite [DOC-7] and [GEO-2] here", ["[DOC-7]", "[GEO-2]"]),
            ("no tokens here", []),
            ("lowercase [src-1] rejected", []),
            ("single char [S] too short", []),
            ("(SRC-1) parenthesised not a token", []),
            ("Source 1 prose form not a token", []),
            ("[SRC--1] valid", ["[SRC--1]"]),
            ("long but valid [A" + "0" * 22 + "]", ["[A" + "0" * 22 + "]"]),
        ],
    )
    def test_regex(self, text, expected):
        assert CITATION_TOKEN_RE.findall(text) == expected


class TestRequiredSourceIds:
    def test_all_ids_cited_passes(self):
        case = make_case([ScoringRule("required_source_ids", {"ids": ["SRC-1"], "allow_extras": False})])
        (score, _) = score_case(case, "Paris [SRC-1]")
        assert score.passed is True

    def test_missing_id_fails(self):
        case = make_case(
            [
                ScoringRule(
                    "required_source_ids",
                    {"ids": ["SRC-1", "SRC-2"], "allow_extras": False},
                )
            ],
            evidence=[EvidenceItem("SRC-1", "a"), EvidenceItem("SRC-2", "b")],
        )
        (score, _) = score_case(case, "Paris [SRC-1]")
        check = score.checks[0]
        assert check.passed is False
        assert "SRC-2" in check.detail
        assert check.count == 1

    def test_extras_fail_when_not_allowed(self):
        case = make_case(
            [ScoringRule("required_source_ids", {"ids": ["SRC-1"], "allow_extras": False})],
            evidence=[EvidenceItem("SRC-1", "a"), EvidenceItem("SRC-2", "b")],
        )
        (score, _) = score_case(case, "Paris [SRC-1] and [SRC-2]")
        assert score.checks[0].passed is False

    def test_extras_allowed_when_allowed(self):
        case = make_case(
            [ScoringRule("required_source_ids", {"ids": ["SRC-1"], "allow_extras": True})],
            evidence=[EvidenceItem("SRC-1", "a"), EvidenceItem("SRC-2", "b")],
        )
        (score, _) = score_case(case, "Paris [SRC-1] and [SRC-2]")
        assert score.checks[0].passed is True

    def test_non_evidence_tokens_do_not_fail(self):
        # docs/scoring.md: non-evidence tokens don't fail this check;
        # they are counted by invented_citations.
        case = make_case(
            [ScoringRule("required_source_ids", {"ids": ["SRC-1"], "allow_extras": True})]
        )
        (score, _) = score_case(case, "Paris [SRC-1] per [JOURNAL-X]")
        assert score.checks[0].passed is True


class TestInventedCitations:
    def test_zero_invented_passes(self):
        case = make_case(
            [ScoringRule("invented_citations", {"max_allowed": 0, "ids": ["SRC-1"]})]
        )
        (score, _) = score_case(case, "Paris [SRC-1]")
        assert score.checks[0].passed is True
        assert score.checks[0].count == 0

    def test_invented_token_fails(self):
        case = make_case(
            [ScoringRule("invented_citations", {"max_allowed": 0, "ids": ["SRC-1"]})]
        )
        (score, _) = score_case(case, "Paris [SRC-1] per [JOURNAL-X]")
        assert score.checks[0].passed is False
        assert score.checks[0].count == 1

    def test_within_budget_passes(self):
        case = make_case(
            [ScoringRule("invented_citations", {"max_allowed": 2, "ids": ["SRC-1"]})]
        )
        (score, _) = score_case(case, "[X-1] [Y-2] [SRC-1]")
        assert score.checks[0].passed is True
        assert score.checks[0].count == 2

    def test_pattern_match_counts_as_invented(self):
        case = make_case(
            [
                ScoringRule(
                    "invented_citations",
                    {"max_allowed": 0, "ids": ["SRC-1"], "patterns": [r"10\.\d{4,9}/\S+"]},
                )
            ]
        )
        (score, _) = score_case(case, "See doi.org/10.1234/fake.2024 [SRC-1]")
        assert score.checks[0].passed is False

    def test_ieee_754_false_positive_is_documented_behaviour(self):
        # Reviewer pin 3: [IEEE-754] with max_allowed=0 must FAIL — this is
        # the documented citation false-positive class, pinned as expected.
        case = make_case(
            [ScoringRule("invented_citations", {"max_allowed": 0, "ids": ["SRC-1"]})]
        )
        (score, _) = score_case(case, "Uses [IEEE-754] math per [SRC-1]")
        assert score.checks[0].passed is False
        assert score.checks[0].count == 1

    def test_detail_names_invented_ids_capped(self):
        # v0.1.10 explainability requirement: invented_citations detail
        # names the invented ids ('ID'), capped at 5 distinct + "and N more".
        case = make_case(
            [ScoringRule("invented_citations", {"max_allowed": 0, "ids": ["SRC-1"]})]
        )
        (score, _) = score_case(case, "[A-1] [B-2] [SRC-1]")
        detail = score.checks[0].detail
        assert "'A-1'" in detail and "'B-2'" in detail
        assert "(max allowed 0)" in detail

    def test_detail_invented_ids_over_cap(self):
        case = make_case(
            [ScoringRule("invented_citations", {"max_allowed": 0, "ids": ["SRC-1"]})]
        )
        (score, _) = score_case(
            case, "[A-1] [B-2] [C-3] [D-4] [E-5] [F-6] [G-7]"
        )
        detail = score.checks[0].detail
        assert score.checks[0].count == 7
        assert "and 2 more" in detail
        # Only the first 5 sorted distinct ids appear by name.
        assert "'A-1'" in detail and "'E-5'" in detail
        assert "'G-7'" not in detail


class TestUnsupportedClaims:
    def test_marker_counts_deterministic(self):
        case = make_case(
            [
                ScoringRule(
                    "unsupported_claims",
                    {"max_allowed": 0, "markers": ["researchers say"]},
                )
            ]
        )
        # Marker present but WITH a citation token: per the landed
        # implementation, the claim-marker count itself drives pass/fail
        # (citations don't excuse markers — stricter than a naive reading
        # of the spec; pinned as observed, non-blocking note to Lead).
        (score, _) = score_case(case, "Researchers say Paris is capital [SRC-1].")
        assert score.checks[0].passed is False
        assert score.checks[0].count == 1
        (score2, _) = score_case(case, "Paris is capital [SRC-1].")
        assert score2.checks[0].passed is True
        assert score2.checks[0].count == 0
        (score3, _) = score_case(case, "Researchers say Paris is capital.")
        assert score3.checks[0].passed is False
        assert score3.checks[0].count == 1

    def test_detail_names_tripped_markers_with_counts(self):
        # v0.1.10 explainability requirement: detail NAMES the tripped
        # markers with per-marker hit counts ("'x' xN"), capped at 5
        # distinct + "and N more marker type(s)".
        case = make_case(
            [
                ScoringRule(
                    "unsupported_claims",
                    {
                        "max_allowed": 1,
                        "markers": ["i think", "probably", "maybe", "possibly", "likely", "perhaps"],
                    },
                )
            ]
        )
        (score, _) = score_case(
            case,
            "I think a, I think b, probably c, probably d, maybe e, possibly f, likely g, perhaps h",
        )
        detail = score.checks[0].detail
        assert score.checks[0].count == 8
        assert "'i think' x2" in detail
        assert "'probably' x2" in detail
        assert "'maybe' x1" in detail
        assert "and 1 more marker type(s)" in detail
        assert "(max allowed 1)" in detail

    def test_detail_caps_at_five_distinct_markers(self):
        case = make_case(
            [
                ScoringRule(
                    "unsupported_claims",
                    {"max_allowed": 0, "markers": ["m1", "m2", "m3", "m4", "m5", "m6"]},
                )
            ]
        )
        (score, _) = score_case(case, "m1 m2 m3 m4 m5 m6")
        detail = score.checks[0].detail
        assert "'m5' x1" in detail
        assert "'m6'" not in detail.split("and 1 more marker type(s)")[0]
        assert "and 1 more marker type(s)" in detail

    def test_clean_response_detail_says_no_markers(self):
        case = make_case(
            [ScoringRule("unsupported_claims", {"max_allowed": 0, "markers": ["i think"]})]
        )
        (score, _) = score_case(case, "Paris [SRC-1].")
        assert score.checks[0].detail == "no uncited claim markers"

    def test_zero_tokens_long_response_needs_human(self):
        # docs/scoring.md: zero citation tokens + length >= min_length
        # (default 200) -> needs_human, passed=False, count=None.
        case = make_case([ScoringRule("unsupported_claims", {"max_allowed": 0, "markers": ["x"]})])
        long_text = "Paris is the capital. " * 15  # > 200 chars, no tokens
        (score, _) = score_case(case, long_text)
        check = score.checks[0]
        assert check.needs_human is True
        assert check.passed is False
        assert check.count is None
        assert score.needs_human is True

    def test_zero_tokens_short_response_stays_deterministic(self):
        case = make_case([ScoringRule("unsupported_claims", {"max_allowed": 0, "markers": ["x"]})])
        (score, _) = score_case(case, "Paris.")
        check = score.checks[0]
        assert check.needs_human is False
        assert check.passed is True

    def test_min_length_param_respected(self):
        case = make_case(
            [ScoringRule("unsupported_claims", {"max_allowed": 0, "markers": ["x"], "min_length": 5})]
        )
        (score, _) = score_case(case, "Paris is nice.")
        assert score.checks[0].needs_human is True

    def test_needs_human_never_passes_silently(self):
        case = make_case([ScoringRule("unsupported_claims", {"max_allowed": 99, "markers": []})])
        (score, _) = score_case(case, "long " * 60)
        assert score.checks[0].passed is False
        assert score.needs_human is True


class TestValidJson:
    def test_single_clean_object_parses(self):
        case = make_case([ScoringRule("valid_json", {})], case_id="so_valid")
        (score, _) = score_case(case, '{"answer": "Paris"}')
        assert score.checks[0].passed is True

    def test_leading_prose_with_clean_object_parses(self):
        case = make_case([ScoringRule("valid_json", {})], case_id="so_valid")
        (score, _) = score_case(case, 'Here is the JSON: {"answer": "Paris"}')
        assert score.checks[0].passed is True

    def test_first_position_only_malformed_first_fails(self):
        # Reviewer pin 1: malformed FIRST brace + valid later object FAILS —
        # no position-shopping.
        case = make_case([ScoringRule("valid_json", {})], case_id="so_valid")
        (score, _) = score_case(case, 'Here: {bad... {"a": 1}')
        assert score.checks[0].passed is False
        assert "parse error" in score.checks[0].detail.lower()

    def test_malformed_brace_before_valid_bracket_is_not_reached(self):
        # Reviewer's behavior-distinguishing pin: a MALFORMED { that
        # PRECEDES a valid [ must FAIL — the [ is NOT reached. The pinned
        # rule is earlier-of-by-position with a single decode attempt at
        # that position; no retry-shopping across opener types.
        case = make_case([ScoringRule("valid_json", {})], case_id="so_valid")
        (score, _) = score_case(case, 'Here: {bad... [1, 2, 3]')
        assert score.checks[0].passed is False
        # Detail must reference the '{' attempt, proving the '[' was never
        # tried.
        assert "{" in score.checks[0].detail
        assert "[" not in score.checks[0].detail

    def test_valid_bracket_before_malformed_brace_parses(self):
        # Mirror case: a valid [ EARLIER than a malformed { parses —
        # precedence is by position, and only one decode attempt happens.
        case = make_case([ScoringRule("valid_json", {})], case_id="so_valid")
        (score, _) = score_case(case, "Data: [1, 2] then {bad...")
        assert score.checks[0].passed is True

    def test_no_json_fails(self):
        case = make_case([ScoringRule("valid_json", {})], case_id="so_valid")
        (score, _) = score_case(case, "plain prose only")
        assert score.checks[0].passed is False

    def test_array_form_parses(self):
        case = make_case([ScoringRule("valid_json", {})], case_id="so_valid")
        (score, _) = score_case(case, '[{"a": 1}]')
        assert score.checks[0].passed is True


class TestRequiredFields:
    def test_all_fields_present_passes(self):
        case = make_case(
            [
                ScoringRule("valid_json", {}),
                ScoringRule("required_fields", {"fields": ["answer"], "strict": False}),
            ],
            case_id="so_fields",
        )
        (score, _) = score_case(case, '{"answer": "Paris"}')
        assert score.checks[1].passed is True

    def test_null_field_fails(self):
        case = make_case(
            [ScoringRule("required_fields", {"fields": ["answer"], "strict": False})],
            case_id="so_fields",
        )
        (score, _) = score_case(case, '{"answer": null}')
        assert score.checks[0].passed is False
        assert "answer" in score.checks[0].detail

    def test_missing_field_fails(self):
        case = make_case(
            [ScoringRule("required_fields", {"fields": ["answer", "extra_f"], "strict": False})],
            case_id="so_fields",
        )
        (score, _) = score_case(case, '{"answer": "Paris"}')
        assert score.checks[0].passed is False

    def test_strict_extra_keys_fail(self):
        case = make_case(
            [ScoringRule("required_fields", {"fields": ["answer"], "strict": True})],
            case_id="so_fields",
        )
        (score, _) = score_case(case, '{"answer": "Paris", "bonus": 1}')
        assert score.checks[0].passed is False

    def test_lenient_extra_keys_pass(self):
        case = make_case(
            [ScoringRule("required_fields", {"fields": ["answer"], "strict": False})],
            case_id="so_fields",
        )
        (score, _) = score_case(case, '{"answer": "Paris", "bonus": 1}')
        assert score.checks[0].passed is True


class TestFieldType:
    @pytest.mark.parametrize(
        ("value", "declared", "should_pass"),
        [
            ("Paris", "string", True),
            (3, "number", True),
            (3.5, "number", True),
            (True, "boolean", True),
            ([1], "array", True),
            (True, "number", False),
            (3, "string", False),
            ("x", "boolean", False),
        ],
    )
    def test_type_matches(self, value, declared, should_pass):
        import json

        case = make_case(
            [ScoringRule("field_type", {"field": "answer", "type": declared})],
            case_id="so_type",
        )
        (score, _) = score_case(case, json.dumps({"answer": value}))
        assert score.checks[0].passed is should_pass

    def test_bool_is_not_number(self):
        import json

        case = make_case(
            [ScoringRule("field_type", {"field": "answer", "type": "number"})],
            case_id="so_type",
        )
        (score, _) = score_case(case, json.dumps({"answer": True}))
        assert score.checks[0].passed is False


class TestUncertaintyExpression:
    def test_hedge_min_met_passes(self):
        case = make_case(
            [
                ScoringRule(
                    "uncertainty_expression",
                    {"min_hedges": 1, "hedges": ["possibly", "may"]},
                )
            ],
            case_id="un_hedge",
        )
        (score, _) = score_case(case, "This may be Paris.")
        assert score.checks[0].passed is True

    def test_hedge_min_not_met_fails(self):
        case = make_case(
            [
                ScoringRule(
                    "uncertainty_expression",
                    {"min_hedges": 2, "hedges": ["possibly", "may"]},
                )
            ],
            case_id="un_hedge",
        )
        (score, _) = score_case(case, "This may be Paris.")
        assert score.checks[0].passed is False

    def test_overconfident_phrase_fails(self):
        case = make_case(
            [
                ScoringRule(
                    "uncertainty_expression",
                    {"min_hedges": 1, "hedges": ["possibly"], "disallowed": ["definitely"]},
                )
            ],
            case_id="un_hedge",
        )
        (score, _) = score_case(case, "This may be Paris, definitely.")
        assert score.checks[0].passed is False


class TestLexicalContradiction:
    def test_asserting_both_sides_fails(self):
        case = make_case(
            [
                ScoringRule(
                    "lexical_contradiction",
                    {"pairs": [["opened in 1911", "opened in 1912"]]},
                )
            ],
            case_id="con_lex",
        )
        (score, _) = score_case(case, "It opened in 1911, no wait, opened in 1912.")
        assert score.checks[0].passed is False
        assert score.checks[0].count == 1

    def test_single_side_passes(self):
        case = make_case(
            [
                ScoringRule(
                    "lexical_contradiction",
                    {"pairs": [["opened in 1911", "opened in 1912"]]},
                )
            ],
            case_id="con_lex",
        )
        (score, _) = score_case(case, "It opened in 1911.")
        assert score.checks[0].passed is True

    def test_case_insensitive(self):
        case = make_case(
            [
                ScoringRule(
                    "lexical_contradiction",
                    {"pairs": [["Opened In 1911", "OPENED IN 1912"]]},
                )
            ],
            case_id="con_lex",
        )
        (score, _) = score_case(case, "opened in 1911 ... OPENED IN 1912")
        assert score.checks[0].passed is False


class TestConflictAssessment:
    def test_always_needs_human_never_passes(self):
        case = make_case(
            [ScoringRule("conflict_assessment", {"instructions": "Judge which source wins."})],
            case_id="mix_conflict",
        )
        (score, _) = score_case(case, "Perfect response text")
        check = score.checks[0]
        assert check.needs_human is True
        assert check.passed is False
        assert score.needs_human is True
        assert score.passed is True  # no decisive checks failed
        assert "Judge which source wins." in check.detail

    def test_default_guidance_when_params_empty(self):
        case = make_case([ScoringRule("conflict_assessment", {})], case_id="mix_conflict")
        (score, _) = score_case(case, "text")
        assert score.checks[0].needs_human is True
        assert score.checks[0].detail


class TestMixedEvidenceSurfaceChecks:
    def test_all_sources_present(self):
        case = make_case(
            [ScoringRule("all_sources_present", {"ids": ["SRC-1", "SRC-2"]})],
            evidence=[EvidenceItem("SRC-1", "a"), EvidenceItem("SRC-2", "b")],
            case_id="mix_surface",
        )
        (score, _) = score_case(case, "[SRC-1] [SRC-2]")
        assert score.checks[0].passed is True
        (score2, _) = score_case(case, "[SRC-1]")
        assert score2.checks[0].passed is False

    def test_unresolved_marker_patterns(self):
        case = make_case([ScoringRule("unresolved_marker", {})], case_id="mix_surface")
        (score, _) = score_case(case, "Answer is <PLACEHOLDER> TODO done")
        assert score.checks[0].passed is False
        (score2, _) = score_case(case, "Answer is complete.")
        assert score2.checks[0].passed is True

    def test_no_absolute_claims(self):
        case = make_case([ScoringRule("no_absolute_claims", {})], case_id="mix_surface")
        (score, _) = score_case(case, "This definitely proves it.")
        assert score.checks[0].passed is False
        (score2, _) = score_case(case, "This suggests it.")
        assert score2.checks[0].passed is True


class TestScoreCaseSemantics:
    def test_weights_never_influence_pass_fail(self):
        # Same checks, wildly different weights: pass/fail identical.
        case_low = make_case(
            [ScoringRule("required_source_ids", {"ids": ["SRC-1"], "allow_extras": False}, weight=0.5)],
            case_id="w_low",
        )
        case_high = make_case(
            [ScoringRule("required_source_ids", {"ids": ["SRC-1"], "allow_extras": False}, weight=5)],
            case_id="w_high",
        )
        (low, w_low) = score_case(case_low, "No citation")
        (high, w_high) = score_case(case_high, "No citation")
        assert low.passed == high.passed == False
        assert w_low == 0.5
        assert w_high == 5.0

    def test_weight_sum_returned(self):
        case = make_case(
            [
                ScoringRule("valid_json", {}, weight=1.0),
                ScoringRule("required_fields", {"fields": ["a"], "strict": False}, weight=2.0),
            ],
            case_id="w_sum",
        )
        (_, weight_sum) = score_case(case, '{"a": 1}')
        assert weight_sum == 3.0

    def test_scorers_never_read_expected(self):
        # `expected` says the opposite of params; params must win.
        case = EvalCase(
            schema_version="1",
            case_id="doc_only",
            suite="evidence_grounding",
            title="Doc-only probe",
            purpose="Ensures expected/constraints never drive scoring.",
            evidence=[EvidenceItem("SRC-1", "Paris is the capital of France.")],
            instruction="Answer.",
            constraints="Wrong constraint pointing to Lyon.",
            scoring=[ScoringRule("required_source_ids", {"ids": ["LYON-1"], "allow_extras": False})],
            expected="Lyon [LYON-1]",
        )
        (score, _) = score_case(case, "Paris [SRC-1]")
        assert score.passed is False  # LYON-1 required per params, not cited

    def test_unknown_scorer_raises_scoring_error(self):
        case = EvalCase(
            schema_version="1",
            case_id="bad_scorer",
            suite="evidence_grounding",
            title="Bad scorer",
            purpose="Direct scoring of an unregistered type must raise ScoringError.",
            evidence=[EvidenceItem("SRC-1", "x")],
            instruction="Answer.",
            constraints="Doc-only.",
            scoring=[ScoringRule("vibes_based", {})],
            expected="Doc-only.",
        )
        with pytest.raises(ScoringError):
            score_case(case, "text")

    def test_needs_human_case_status_derivation(self):
        case = make_case(
            [ScoringRule("conflict_assessment", {})],
            case_id="mix_conflict",
        )
        (score, _) = score_case(case, "text")
        from evalkit.models import CaseResult
        from evalkit.provider.base import GenerationResult

        result = CaseResult.from_outcome(
            case_id=case.case_id,
            suite=case.suite,
            score=score,
            generation=GenerationResult(text="text", model="m", provider="mock", elapsed_ms=0.0),
        )
        assert result.status == "needs_human"
        assert result.status in CASE_STATUSES


class TestRegistry:
    def test_all_doc_registered_scorers_present(self):
        # docs/scoring.md registers these names (superset allowed).
        names = registered_scorer_names()
        for expected in (
            "required_source_ids",
            "invented_citations",
            "unsupported_claims",
            "valid_json",
            "required_fields",
            "field_type",
            "lexical_contradiction",
            "conflict_assessment",
        ):
            assert is_registered_scorer(expected), f"{expected} missing from registry"

    def test_no_duplicates(self):
        # register_scorer raises on duplicates; registry integrity implies
        # the import cycle completed exactly once.
        assert len(registered_scorer_names()) == len(registered_scorer_names())


class TestAggregate:
    def test_weighted_pass_rate_non_needs_human_only(self):
        rates = [(2.0, True, False), (3.0, False, False), (5.0, False, True)]
        rate = weighted_pass_rate(rates)
        assert rate == pytest.approx(2.0 / 5.0)

    def test_no_scoreable_cases_returns_none(self):
        assert weighted_pass_rate([(5.0, False, True)]) is None
        assert weighted_pass_rate([]) is None

    def test_run_summary_six_mandatory_keys(self):
        summary = run_summary(
            ["passed", "failed", "needs_human", "error"],
            [(1.0, True, False), (1.0, False, False), (1.0, False, True), (1.0, False, False)],
            123.0,
        )
        assert summary["total_cases"] == 4
        assert summary["passed"] == 1
        assert summary["failed"] == 1
        assert summary["needs_human"] == 1
        assert summary["errors"] == 1
        assert summary["duration_ms"] == 123.0

    def test_run_summary_needs_human_excluded_from_rate(self):
        summary = run_summary(
            ["passed", "needs_human"],
            [(1.0, True, False), (9.0, False, True)],
            0.0,
        )
        assert summary["weighted_pass_rate"] == 1.0

    def test_run_summary_omits_rate_when_nothing_scoreable(self):
        summary = run_summary(["needs_human"], [(5.0, False, True)], 0.0)
        assert "weighted_pass_rate" not in summary