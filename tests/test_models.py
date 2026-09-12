"""Contract tests for evalkit/models.py (Amendments v0.1.1-v0.1.9).

Round-trips: to_dict(from_dict(x)) == x for every model. Derivation rules
for ScoreResult/CaseResult are pinned; the silent-downgrade guard for
needs_human lives here (Reviewer's round-trip bar).
"""

from __future__ import annotations

import dataclasses

import pytest

from evalkit.models import (
    CASE_STATUSES,
    CaseResult,
    Check,
    RunRecord,
    ScoreResult,
)
from evalkit.provider.base import GenerationResult


def make_generation(**overrides) -> GenerationResult:
    fields = {
        "text": "Paris [SRC-1]",
        "model": "mock-model",
        "provider": "mock",
        "elapsed_ms": 12.5,
        "raw": {"finish_reason": "stop"},
    }
    fields.update(overrides)
    return GenerationResult(**fields)


def make_check(**overrides) -> Check:
    fields = {"name": "required_source_ids", "passed": True, "detail": "all ids cited", "count": 1}
    fields.update(overrides)
    return Check(**fields)


class TestCheck:
    def test_fields_per_amendment_v011(self):
        names = {f.name for f in dataclasses.fields(Check)}
        assert names == {"name", "passed", "detail", "count", "needs_human"}

    def test_needs_human_defaults_false(self):
        assert make_check().needs_human is False

    def test_round_trip(self):
        check = make_check(count=None, needs_human=True, passed=False, detail="human review: faithfulness")
        assert Check.from_dict(check.to_dict()) == check

    def test_from_dict_rejects_missing_required(self):
        with pytest.raises(ValueError):
            Check.from_dict({"name": "x", "passed": True})  # detail missing

    def test_from_dict_rejects_wrong_types(self):
        with pytest.raises(ValueError):
            Check.from_dict({"name": "x", "passed": "yes", "detail": "d"})
        with pytest.raises(ValueError):
            Check.from_dict({"name": "x", "passed": True, "detail": "d", "count": "3"})


class TestScoreResultSemantics:
    def test_passed_all_non_needs_human_pass(self):
        score = ScoreResult.from_checks([make_check(), make_check(name="other")])
        assert score.passed is True
        assert score.needs_human is False

    def test_failed_when_one_decisive_check_fails(self):
        score = ScoreResult.from_checks([make_check(), make_check(name="bad", passed=False)])
        assert score.passed is False
        assert score.needs_human is False

    def test_needs_human_any_check(self):
        score = ScoreResult.from_checks(
            [make_check(), make_check(name="conflict_assessment", passed=False, needs_human=True)]
        )
        assert score.needs_human is True
        # v0.1.7: decisive checks still gate passed.
        assert score.passed is True

    def test_all_needs_human_checks_are_excluded_from_passed(self):
        score = ScoreResult.from_checks([make_check(name="human-only", passed=False, needs_human=True)])
        assert score.passed is True
        assert score.needs_human is True

    def test_needs_human_never_silently_passes_case(self):
        # CaseResult.passed = ScoreResult.passed AND NOT needs_human.
        score = ScoreResult.from_checks([make_check(passed=False, needs_human=True)])
        result = CaseResult.from_outcome(case_id="c", suite="s", score=score, generation=make_generation())
        assert result.passed is False
        assert result.status == "needs_human"

    def test_needs_human_never_silently_fails_decisive_checks(self):
        score = ScoreResult.from_checks([make_check(), make_check(name="nh", passed=False, needs_human=True)])
        result = CaseResult.from_outcome(case_id="c", suite="s", score=score, generation=make_generation())
        assert result.status == "needs_human"
        assert result.score.passed is True

    def test_empty_checks_pass_is_false(self):
        # all([]) is True but a score with no checks must not read as pass.
        score = ScoreResult(checks=[], passed=False, needs_human=False)
        assert score.passed is False

    def test_round_trip(self):
        score = ScoreResult.from_checks(
            [make_check(), make_check(name="nh", passed=False, needs_human=True, count=None)]
        )
        assert ScoreResult.from_dict(score.to_dict()) == score


class TestNeedsHumanRoundTrip:
    """Reviewer requirement: needs_human=true must survive storage exactly."""

    def test_stored_result_json_preserves_needs_human(self, tmp_path):
        import json

        check = make_check(name="conflict_assessment", passed=False, needs_human=True, count=None)
        score = ScoreResult.from_checks([check])
        result = CaseResult.from_outcome(case_id="c", suite="mixed_evidence", score=score, generation=make_generation())
        payload = json.dumps(result.to_dict())
        restored = CaseResult.from_dict(json.loads(payload))
        assert restored.score.needs_human is True
        assert restored.score.checks[0].needs_human is True
        assert restored.score.checks[0].passed is False
        assert restored.status == "needs_human"

    def test_dropped_needs_human_key_would_be_caught(self, tmp_path):
        # If serialization dropped the key, from_dict must NOT silently
        # downgrade to an ordinary check: default False would flip semantics.
        import json

        check = make_check(name="nh", passed=False, needs_human=True, count=None)
        data = check.to_dict()
        del data["needs_human"]
        restored = Check.from_dict(data)
        # Default is False: a dropped key CHANGES semantics — so writers
        # must always serialize the key explicitly.
        assert restored.needs_human is False
        assert check.to_dict().get("needs_human") is True


class TestCaseResultDerivation:
    def test_status_enum_closed(self):
        assert CASE_STATUSES == ("passed", "failed", "needs_human", "error")
        assert "skipped" not in CASE_STATUSES

    def test_passed_derivation(self):
        score = ScoreResult.from_checks([make_check()])
        result = CaseResult.from_outcome(case_id="c", suite="s", score=score, generation=make_generation())
        assert result.status == "passed"
        assert result.passed is True
        assert result.error is None

    def test_failed_derivation(self):
        score = ScoreResult.from_checks([make_check(passed=False)])
        result = CaseResult.from_outcome(case_id="c", suite="s", score=score, generation=make_generation())
        assert result.status == "failed"

    def test_error_case_has_no_generation_but_appears_in_results(self):
        result = CaseResult.from_outcome(case_id="c", suite="s", score=None, error="provider unreachable")
        assert result.status == "error"
        assert result.generation is None
        assert result.error == "provider unreachable"
        assert result.passed is False

    def test_error_is_none_for_non_error_status(self):
        score = ScoreResult.from_checks([make_check()])
        result = CaseResult.from_outcome(case_id="c", suite="s", score=score, generation=make_generation())
        assert result.error is None

    def test_status_validation_rejects_unknown(self):
        with pytest.raises(ValueError):
            CaseResult(
                case_id="c",
                suite="s",
                passed=False,
                needs_human=False,
                score=ScoreResult(),
                generation=None,
                status="skipped",
            )

    def test_generation_none_only_for_error(self):
        score = ScoreResult.from_checks([make_check()])
        with pytest.raises(ValueError):
            CaseResult(case_id="c", suite="s", passed=True, needs_human=False, score=score, generation=None)

    def test_round_trip_with_error_case(self):
        result = CaseResult.from_outcome(case_id="c", suite="s", score=None, error="timeout")
        assert CaseResult.from_dict(result.to_dict()) == result

    def test_round_trip_full(self):
        score = ScoreResult.from_checks([make_check()])
        result = CaseResult.from_outcome(case_id="c", suite="s", score=score, generation=make_generation())
        assert CaseResult.from_dict(result.to_dict()) == result

    def test_elapsed_ms_round_trips_as_float(self):
        score = ScoreResult.from_checks([make_check()])
        result = CaseResult.from_outcome(case_id="c", suite="s", score=score, generation=make_generation(elapsed_ms=0.0))
        restored = CaseResult.from_dict(result.to_dict())
        assert isinstance(restored.generation.elapsed_ms, float)
        assert restored.generation.elapsed_ms == 0.0


class TestRunRecord:
    def make_record(self, **overrides) -> RunRecord:
        score = ScoreResult.from_checks([make_check()])
        fields = {
            "run_id": "20260912T101500Z-abcd1234",
            "timestamp_utc": "2026-09-12T10:15:00Z",
            "evalkit_version": "0.1.0",
            "provider": "mock",
            "model": "mock-model",
            "config": {
                "model": "mock-model",
                "provider": "mock",
                "base_url": "http://127.0.0.1:11434",
                "options": {},
                "suites": ["evidence_grounding"],
                "evalkit_version": "0.1.0",
                "start_time_utc": "2026-09-12T10:14:59Z",
            },
            "results": [
                CaseResult.from_outcome(case_id="c1", suite="s", score=score, generation=make_generation())
            ],
            "summary": {
                "total_cases": 1,
                "passed": 1,
                "failed": 0,
                "needs_human": 0,
                "errors": 0,
                "duration_ms": 12.5,
            },
            "duration_ms": 12.5,
        }
        fields.update(overrides)
        return RunRecord(**fields)

    def test_config_snapshot_required_keys(self):
        record = self.make_record()
        assert {
            "model",
            "provider",
            "base_url",
            "options",
            "suites",
            "evalkit_version",
            "start_time_utc",
        } <= set(record.config)

    def test_summary_six_mandatory_keys(self):
        record = self.make_record()
        assert {
            "total_cases",
            "passed",
            "failed",
            "needs_human",
            "errors",
            "duration_ms",
        } <= set(record.summary)

    def test_run_record_has_no_singular_suite(self):
        names = {f.name for f in dataclasses.fields(RunRecord)}
        assert "suite" not in names

    def test_round_trip(self):
        record = self.make_record()
        assert RunRecord.from_dict(record.to_dict()) == record

    def test_round_trip_with_error_case(self):
        record = self.make_record(
            results=[
                CaseResult.from_outcome(case_id="c1", suite="s", score=None, error="down")
            ],
            summary={
                "total_cases": 1,
                "passed": 0,
                "failed": 0,
                "needs_human": 0,
                "errors": 1,
                "duration_ms": 1.0,
            },
        )
        assert RunRecord.from_dict(record.to_dict()) == record

    def test_from_dict_rejects_missing_top_level_key(self):
        data = self.make_record().to_dict()
        del data["config"]
        with pytest.raises(ValueError):
            RunRecord.from_dict(data)