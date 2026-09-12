"""Compare contract tests (R5): comparability guard, per-case status
pairs, summary deltas, render safety."""

from __future__ import annotations

import pytest

from evalkit.compare import compare_runs
from evalkit.errors import CompareError
from evalkit.models import CaseResult, RunRecord, ScoreResult, Check
from evalkit.provider.base import GenerationResult


def make_record(
    run_id="20260912T000000Z-aaa10000",
    model="mock-model",
    options=None,
    suites=("evidence_grounding",),
    results=None,
    summary=None,
    version="0.1.0",
) -> RunRecord:
    if results is None:
        generation = GenerationResult(text="t", model=model, provider="mock", elapsed_ms=0.0)
        score = ScoreResult.from_checks([Check(name="x", passed=True, detail="d")])
        results = [
            CaseResult.from_outcome(case_id="c1", suite="evidence_grounding", score=score, generation=generation)
        ]
    if summary is None:
        summary = {
            "total_cases": len(results),
            "passed": sum(1 for r in results if r.status == "passed"),
            "failed": sum(1 for r in results if r.status == "failed"),
            "needs_human": sum(1 for r in results if r.status == "needs_human"),
            "errors": sum(1 for r in results if r.status == "error"),
            "duration_ms": 1.0,
        }
    return RunRecord(
        run_id=run_id,
        timestamp_utc="2026-09-12T00:00:00Z",
        evalkit_version=version,
        provider="mock",
        model=model,
        config={
            "model": model,
            "provider": "mock",
            "base_url": "http://127.0.0.1:11434",
            "options": options or {},
            "suites": list(suites),
            "evalkit_version": version,
            "start_time_utc": "2026-09-12T00:00:00Z",
        },
        results=results,
        summary=summary,
        duration_ms=1.0,
    )


class TestComparabilityGuard:
    def test_mismatched_model_refuses(self):
        a = make_record(run_id="a", model="model-a")
        b = make_record(run_id="b", model="model-b")
        with pytest.raises(CompareError) as excinfo:
            compare_runs(a, b)
        assert "model" in str(excinfo.value)

    def test_mismatched_provider_refuses(self):
        a = make_record(run_id="a")
        b = make_record(run_id="b")
        b = RunRecord(
            run_id=b.run_id,
            timestamp_utc=b.timestamp_utc,
            evalkit_version=b.evalkit_version,
            provider="ollama",
            model=b.model,
            config={**b.config, "provider": "ollama"},
            results=b.results,
            summary=b.summary,
            duration_ms=b.duration_ms,
        )
        with pytest.raises(CompareError):
            compare_runs(a, b)

    def test_mismatched_base_url_refuses(self):
        a = make_record(run_id="a")
        b = make_record(run_id="b")
        b = RunRecord(
            run_id=b.run_id,
            timestamp_utc=b.timestamp_utc,
            evalkit_version=b.evalkit_version,
            provider=b.provider,
            model=b.model,
            config={**b.config, "base_url": "http://127.0.0.1:9999"},
            results=b.results,
            summary=b.summary,
            duration_ms=b.duration_ms,
        )
        with pytest.raises(CompareError):
            compare_runs(a, b)

    def test_mismatched_options_refuse(self):
        a = make_record(run_id="a", options={"temperature": 0.1})
        b = make_record(run_id="b", options={"temperature": 0.9})
        with pytest.raises(CompareError):
            compare_runs(a, b)

    def test_different_suites_refuse(self):
        a = make_record(run_id="a", suites=("evidence_grounding",))
        b = make_record(run_id="b", suites=("contradiction",))
        with pytest.raises(CompareError) as excinfo:
            compare_runs(a, b)
        assert "suites" in str(excinfo.value)

    def test_different_generation_refuses(self):
        a = make_record(run_id="a", version="0.1.0")
        b = make_record(run_id="b", version="0.2.0")
        with pytest.raises(CompareError) as excinfo:
            compare_runs(a, b)
        assert "generations" in str(excinfo.value)

    def test_compatible_runs_compare(self):
        a = make_record(run_id="a")
        b = make_record(run_id="b")
        comparison = compare_runs(a, b)
        assert comparison.comparable is True
        assert comparison.run_id_a == "a"
        assert comparison.run_id_b == "b"


class TestCaseComparison:
    def test_status_change_detected(self):
        generation = GenerationResult(text="t", model="m", provider="mock", elapsed_ms=0.0)
        score_pass = ScoreResult.from_checks([Check(name="x", passed=True, detail="d")])
        score_fail = ScoreResult.from_checks([Check(name="x", passed=False, detail="d")])
        a = make_record(
            run_id="a",
            results=[
                CaseResult.from_outcome(case_id="c1", suite="s", score=score_pass, generation=generation),
                CaseResult.from_outcome(case_id="c2", suite="s", score=score_pass, generation=generation),
            ],
        )
        b = make_record(
            run_id="b",
            results=[
                CaseResult.from_outcome(case_id="c1", suite="s", score=score_fail, generation=generation),
                CaseResult.from_outcome(case_id="c2", suite="s", score=score_pass, generation=generation),
            ],
        )
        comparison = compare_runs(a, b)
        by_id = {c.case_id: c for c in comparison.cases}
        assert by_id["c1"].changed is True
        assert by_id["c1"].status_a == "passed"
        assert by_id["c1"].status_b == "failed"
        assert by_id["c2"].changed is False

    def test_missing_case_in_one_run_reported(self):
        a = make_record(run_id="a")  # has c1
        b = make_record(run_id="b", results=[])  # empty
        comparison = compare_runs(a, b)
        by_id = {c.case_id: c for c in comparison.cases}
        assert by_id["c1"].status_a == "passed"
        assert by_id["c1"].status_b == "missing"
        assert by_id["c1"].changed is True

    def test_summary_deltas_present(self):
        generation = GenerationResult(text="t", model="m", provider="mock", elapsed_ms=0.0)
        score_pass = ScoreResult.from_checks([Check(name="x", passed=True, detail="d")])
        score_fail = ScoreResult.from_checks([Check(name="x", passed=False, detail="d")])
        a = make_record(
            run_id="a",
            results=[CaseResult.from_outcome(case_id="c1", suite="s", score=score_pass, generation=generation)],
        )
        b = make_record(
            run_id="b",
            results=[CaseResult.from_outcome(case_id="c1", suite="s", score=score_fail, generation=generation)],
        )
        comparison = compare_runs(a, b)
        assert comparison.summary_delta["passed"] == {"a": 1, "b": 0}
        assert comparison.summary_delta["failed"] == {"a": 0, "b": 1}

    def test_identical_runs_yield_no_deltas(self):
        a = make_record(run_id="a")
        b = make_record(run_id="b")
        comparison = compare_runs(a, b)
        assert comparison.summary_delta == {}
        assert all(not c.changed for c in comparison.cases)