"""Runner contract tests: degradation rules, prompt construction,
multi-suite runs, weight plumbing, every-started-case-appears rule."""

from __future__ import annotations

import pytest

from evalkit.cases import EvidenceItem, EvalCase, ScoringRule
from evalkit.config import EvalKitConfig
from evalkit.models import RunRecord
from evalkit.provider.base import (
    ProviderConnectionError,
    ProviderProtocolError,
    ProviderTimeout,
)
from evalkit.provider.mock import MockProvider, ScriptedResponse
from evalkit.runner import run_cases, run_suite


def make_case(case_id="rc_1", scoring=None, evidence=None, instruction="Answer with [ID].") -> EvalCase:
    return EvalCase(
        schema_version="1",
        case_id=case_id,
        suite="evidence_grounding",
        title="Runner fixture",
        purpose="Runner behaviour testing.",
        evidence=evidence or [EvidenceItem(id="SRC-1", text="Paris is the capital of France.")],
        instruction=instruction,
        constraints="Doc-only.",
        scoring=scoring
        or [ScoringRule("required_source_ids", {"ids": ["SRC-1"], "allow_extras": False})],
        expected="Doc-only.",
    )


def make_config(provider="mock", model="mock-model") -> EvalKitConfig:
    return EvalKitConfig(provider=provider, model=model)


class TestHappyPath:
    def test_run_suite_scores_every_case(self):
        provider = MockProvider(responses={"Answer with": "Paris [SRC-1]"})
        record = run_suite(
            provider=provider,
            config=make_config(),
            cases=[make_case("rc_1"), make_case("rc_2")],
            suite="evidence_grounding",
        )
        assert len(record.results) == 2
        assert all(r.status == "passed" for r in record.results)

    def test_record_shape_per_contract(self):
        provider = MockProvider(responses={"Answer with": "Paris [SRC-1]"})
        record = run_suite(provider=provider, config=make_config(), cases=[make_case()], suite="s")
        assert record.run_id == ""  # store assigns
        assert record.provider == "mock"
        assert record.model == "mock-model"
        assert record.config["suites"] == ["s"]
        assert set(record.config) >= {
            "model",
            "provider",
            "base_url",
            "options",
            "suites",
            "evalkit_version",
            "start_time_utc",
        }
        assert set(record.summary) >= {
            "total_cases",
            "passed",
            "failed",
            "needs_human",
            "errors",
            "duration_ms",
        }

    def test_instruction_sent_verbatim_plus_evidence(self):
        provider = MockProvider()
        run_suite(provider=provider, config=make_config(), cases=[make_case()], suite="s")
        prompt = provider.calls[0]["prompt"]
        assert prompt.startswith("Answer with [ID].")
        assert "[SRC-1] Paris is the capital of France." in prompt


class TestDegradationRules:
    def test_connection_error_degrades_per_case_suite_continues(self):
        # First call fails; the suite must still run remaining cases.
        # Match key hits the PROMPT (instruction + evidence), so the two
        # cases need distinct instructions for scripting.
        provider = MockProvider(
            responses=[
                ScriptedResponse(match="first case instruction", fail_with=ProviderConnectionError("down"))
            ],
            fallback_text="Paris [SRC-1]",
        )
        record = run_suite(
            provider=provider,
            config=make_config(),
            cases=[
                make_case("rc_1", instruction="first case instruction"),
                make_case("rc_2", instruction="second case instruction"),
            ],
            suite="s",
        )
        assert record.results[0].status == "error"
        assert record.results[0].generation is None
        assert "ProviderConnectionError" in record.results[0].error
        assert record.results[1].status == "passed"
        assert record.summary["errors"] == 1
        assert record.summary["total_cases"] == 2

    def test_timeout_degrades_per_case(self):
        provider = MockProvider(
            responses=[
                ScriptedResponse(match="first case instruction", fail_with=ProviderTimeout("slow"))
            ],
            fallback_text="Paris [SRC-1]",
        )
        record = run_suite(
            provider=provider,
            config=make_config(),
            cases=[make_case("rc_1", instruction="first case instruction")],
            suite="s",
        )
        assert record.results[0].status == "error"
        assert "ProviderTimeout" in record.results[0].error

    def test_protocol_error_degrades_per_case(self):
        provider = MockProvider(
            responses=[
                ScriptedResponse(
                    match="first case instruction", fail_with=ProviderProtocolError("bad body")
                )
            ],
            fallback_text="Paris [SRC-1]",
        )
        record = run_suite(
            provider=provider,
            config=make_config(),
            cases=[make_case("rc_1", instruction="first case instruction")],
            suite="s",
        )
        assert record.results[0].status == "error"

    def test_error_cases_excluded_from_weight_aggregate(self):
        provider = MockProvider(
            responses=[
                ScriptedResponse(match="first case instruction", fail_with=ProviderConnectionError("down"))
            ],
            fallback_text="Paris [SRC-1]",
        )
        record = run_suite(
            provider=provider,
            config=make_config(),
            cases=[
                make_case("rc_1", instruction="first case instruction"),
                make_case("rc_2", instruction="second case instruction"),
            ],
            suite="s",
        )
        # rc_1 errored: only rc_2's weight enters the rate; rc_2 passed -> 1.0.
        assert record.summary["passed"] == 1
        assert record.summary["errors"] == 1
        assert record.summary.get("weighted_pass_rate") == 1.0


class TestStatusDerivation:
    def test_failed_case_recorded(self):
        provider = MockProvider(fallback_text="no citations at all")
        record = run_suite(provider=provider, config=make_config(), cases=[make_case()], suite="s")
        assert record.results[0].status == "failed"
        assert record.summary["failed"] == 1

    def test_needs_human_case_recorded(self):
        provider = MockProvider(fallback_text="x" * 300)  # zero tokens, >= 200 chars
        case = make_case(scoring=[ScoringRule("unsupported_claims", {"max_allowed": 0, "markers": []})])
        record = run_suite(provider=provider, config=make_config(), cases=[case], suite="s")
        assert record.results[0].status == "needs_human"
        assert record.summary["needs_human"] == 1
        # needs_human excluded from weighted pass rate.
        assert "weighted_pass_rate" not in record.summary


class TestMultiSuite:
    def test_run_cases_spans_suites(self):
        provider = MockProvider(fallback_text="Paris [SRC-1]")
        config = make_config()
        suites = {
            "evidence_grounding": [make_case("rc_1")],
            "evidence_grounding_2": [make_case("rc_2")],
        }
        record = run_cases(provider=provider, config=config, suites=suites)
        assert record.summary["total_cases"] == 2
        assert set(record.config["suites"]) == {"evidence_grounding", "evidence_grounding_2"}
        assert [r.case_id for r in record.results] == ["rc_1", "rc_2"]

    def test_determinism_same_inputs_same_statuses(self):
        provider = MockProvider(fallback_text="Paris [SRC-1]")
        cases = [make_case("rc_1"), make_case("rc_2")]
        record_a = run_suite(provider=MockProvider(fallback_text="Paris [SRC-1]"), config=make_config(), cases=cases, suite="s")
        record_b = run_suite(provider=MockProvider(fallback_text="Paris [SRC-1]"), config=make_config(), cases=cases, suite="s")
        assert [r.status for r in record_a.results] == [r.status for r in record_b.results]
        assert record_a.summary["passed"] == record_b.summary["passed"]


class TestUntrustedOutput:
    def test_malicious_output_is_data_never_executed(self):
        payload = '__import__("os").system("del C:\\\\") and Paris [SRC-1]'
        provider = MockProvider(fallback_text=payload)
        record = run_suite(provider=provider, config=make_config(), cases=[make_case()], suite="s")
        # The text is stored verbatim, never executed; scoring is string-only.
        assert record.results[0].generation.text == payload
        assert record.results[0].status == "passed"  # token [SRC-1] present