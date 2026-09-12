"""Report contract tests (F1 gate condition, Lead ruling 2026-09-12).

Covers the F1 fix (option b): RunRecord must validate the SIX mandatory
summary keys (v0.1.3 A3) at both construction and from_dict boundaries,
so a malformed summary (singular 'error' key, missing keys) is rejected
loudly instead of silently rendering ERROR: 0 in terminal_summary.

Also covers terminal_summary rendering for error-heavy runs via the REAL
runner-produced summary shape (scoring.run_summary).
"""

from __future__ import annotations

import pytest

from evalkit.models import CaseResult, RunRecord, ScoreResult
from evalkit.reports import terminal_summary
from evalkit.scoring import run_summary


def make_error_record(summary: dict) -> RunRecord:
    """RunRecord with 3 error-status cases and the given summary dict."""
    results = [
        CaseResult.from_outcome(case_id=f"c{i}", suite="s", score=None, error="provider down")
        for i in range(3)
    ]
    return RunRecord(
        run_id="20260912T000000Z-deadbeef",
        timestamp_utc="2026-09-12T00:00:00Z",
        evalkit_version="0.1.0",
        provider="mock",
        model="mock-model",
        config={
            "model": "mock-model",
            "provider": "mock",
            "base_url": "http://127.0.0.1:11434",
            "options": {},
            "suites": ["s"],
            "evalkit_version": "0.1.0",
            "start_time_utc": "2026-09-12T00:00:00Z",
        },
        results=results,
        summary=summary,
        duration_ms=1.0,
    )


def good_summary() -> dict:
    """The REAL runner-produced shape (scoring.run_summary output)."""
    return run_summary(["error", "error", "error"], [], 1.0)


class TestTerminalSummaryErrorRendering:
    def test_errors_positive_renders_correct_count(self):
        # F1 acceptance criterion: errors>0 renders "ERROR: n" with the
        # correct count for a record built through the real summary path.
        record = make_error_record(good_summary())
        out = terminal_summary(record)
        assert "ERROR: 3" in out
        assert "PASS: 0" in out
        assert "FAIL: 0" in out
        assert "NEEDS HUMAN: 0" in out
        assert "cases: 3" in out

    def test_error_case_lines_render_with_marker_and_error_text(self):
        record = make_error_record(good_summary())
        out = terminal_summary(record)
        assert "[ERR!] c0 — provider down" in out
        assert "[ERR!] c2" in out


class TestRunRecordSummaryValidation:
    """Option (b): the six mandatory keys are enforced at the boundary."""

    MANDATORY = {"total_cases", "passed", "failed", "needs_human", "errors", "duration_ms"}

    def test_good_summary_accepted(self):
        record = make_error_record(good_summary())
        assert self.MANDATORY <= set(record.summary)

    @pytest.mark.parametrize(
        "missing",
        sorted(MANDATORY),
    )
    def test_construction_rejects_summary_missing_mandatory_key(self, missing):
        summary = good_summary()
        del summary[missing]
        with pytest.raises(ValueError) as excinfo:
            make_error_record(summary)
        assert missing in str(excinfo.value)

    def test_singular_error_key_summary_rejected(self):
        # The exact F1 defect class: singular 'error' instead of 'errors'
        # must NOT be silently accepted (it rendered ERROR: 0 before the fix).
        summary = {
            "total_cases": 3,
            "passed": 0,
            "failed": 0,
            "needs_human": 0,
            "error": 3,
            "duration_ms": 1.0,
        }
        with pytest.raises(ValueError) as excinfo:
            make_error_record(summary)
        assert "errors" in str(excinfo.value)

    def test_from_dict_rejects_summary_missing_mandatory_key(self):
        record = make_error_record(good_summary())
        data = record.to_dict()
        del data["summary"]["errors"]
        with pytest.raises(ValueError) as excinfo:
            RunRecord.from_dict(data)
        assert "errors" in str(excinfo.value)

    def test_from_dict_rejects_non_dict_summary(self):
        record = make_error_record(good_summary())
        data = record.to_dict()
        data["summary"] = ["not", "a", "dict"]
        with pytest.raises(ValueError):
            RunRecord.from_dict(data)

    def test_extra_summary_keys_still_allowed(self):
        # Contract: the six are mandatory; extras are permitted.
        summary = good_summary()
        summary["weighted_pass_rate"] = None
        summary["suite_breakdown"] = {"s": {"total": 3}}
        record = make_error_record(summary)
        assert "suite_breakdown" in record.summary

    def test_round_trip_with_validated_summary(self):
        record = make_error_record(good_summary())
        assert RunRecord.from_dict(record.to_dict()) == record


class TestSilentZeroImpossible:
    """The end-to-end F1 regression: no code path may render ERROR: 0
    for a record that actually contains errors."""

    def test_singular_error_summary_cannot_reach_terminal_summary(self):
        # Before the fix: a singular-'error' summary sailed through both
        # boundaries and terminal_summary rendered "ERROR: 0". After the
        # fix it cannot even be constructed.
        summary = {
            "total_cases": 3,
            "passed": 0,
            "failed": 0,
            "needs_human": 0,
            "error": 3,
            "duration_ms": 1.0,
        }
        with pytest.raises(ValueError):
            record = make_error_record(summary)
            terminal_summary(record)  # pragma: no cover - unreachable post-fix


class TestMarkdownReportContent:
    """Content-not-existence asserts for the user-facing Markdown report."""

    def _record(self, statuses):
        from evalkit.provider.base import GenerationResult
        from evalkit.scoring import score_case as _unused  # noqa: F401
        from evalkit.cases import EvidenceItem, EvalCase, ScoringRule
        from evalkit.reports import markdown_report

        generation = GenerationResult(text="Paris [SRC-1]", model="m", provider="mock", elapsed_ms=0.0)
        results = []
        for status in statuses:
            if status == "error":
                results.append(
                    CaseResult.from_outcome(case_id=f"c_{status}_{len(results)}", suite="s", score=None, error="provider unreachable")
                )
                continue
            if status == "needs_human":
                check = __import__("evalkit.models", fromlist=["Check"]).Check(
                    name="conflict_assessment", passed=False, detail="human review", needs_human=True
                )
                score = ScoreResult.from_checks([check])
            else:
                score = ScoreResult.from_checks(
                    [__import__("evalkit.models", fromlist=["Check"]).Check(name="x", passed=status == "passed", detail="d")]
                )
            results.append(
                CaseResult.from_outcome(
                    case_id=f"c_{status}_{len(results)}", suite="s", score=score, generation=generation
                )
            )
        record = make_error_record(
            run_summary([r.status for r in results], [], 2.0)
        )
        record = RunRecord(
            run_id=record.run_id,
            timestamp_utc=record.timestamp_utc,
            evalkit_version=record.evalkit_version,
            provider=record.provider,
            model=record.model,
            config=record.config,
            results=results,
            summary=record.summary,
            duration_ms=record.duration_ms,
        )
        return record, markdown_report(record)

    def test_formula_and_limitations_block_present(self):
        _, md = self._record(["passed"])
        assert "Aggregate formula:" in md
        assert "weighted" in md.lower()
        assert any("limitation" in line.lower() or "not comparable" in line.lower() for line in md.splitlines())

    def test_per_case_table_with_statuses(self):
        _, md = self._record(["passed", "failed"])
        assert "| Case | Suite | Status | Checks |" in md
        assert "| `c_passed_0` | s | passed |" in md
        assert "| `c_failed_1` | s | failed |" in md

    def test_needs_human_section_lists_check_guidance(self):
        _, md = self._record(["needs_human"])
        assert "## Cases needing human review" in md
        assert "**conflict_assessment** (needs human): human review" in md

    def test_error_case_renders_error_text(self):
        _, md = self._record(["error"])
        assert "| `c_error_0` | s | error | provider unreachable |" in md

    def test_failed_check_details_section(self):
        _, md = self._record(["failed"])
        assert "## Failed check details" in md
        assert "**x**: d" in md

    def test_zero_scoreable_cases_wording(self):
        # All-needs_human run: rate must render the documented wording,
        # never 0%/NaN (Reviewer pin 2).
        _, md = self._record(["needs_human"])
        assert "n/a (no scoreable cases" in md
        assert "0.0%" not in md.split("Weighted pass rate")[1].splitlines()[0]

    def test_honesty_note_in_every_report(self):
        _, md = self._record(["passed"])
        assert "## Notes on scoring honesty" in md
        assert "never silently pass or fail" in md

    def test_config_snapshot_fields_in_report(self):
        _, md = self._record(["passed"])
        assert "Base URL: `http://127.0.0.1:11434`" in md
        assert "Suites: s" in md