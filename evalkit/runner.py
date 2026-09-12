"""Evaluation runner: cases + provider -> RunRecord.

Degradation rules (pinned): ANY ProviderError (base class, so future
exception types inherit the behavior) degrades to a per-case
CaseResult with status "error" and the suite continues. Only
config/loading errors abort the whole run (CLI exits 1). Every started
case appears in results, even error cases, so compare denominators stay
stable.

Model output is untrusted input: response text is only ever scored with
string/regex rules or parsed as JSON — never executed, never eval'd.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from . import __version__
from .cases import EvalCase
from .config import EvalKitConfig
from .models import CaseResult, RunRecord
from .provider.base import Provider, ProviderError
from .scoring import run_summary, score_case

__all__ = ["run_suite", "run_cases"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_prompt(case: EvalCase) -> str:
    """Instruction verbatim (contract: never rewritten), evidence appended
    in the case's declared ID format so the model can cite it."""
    lines = [case.instruction, ""]
    for item in case.evidence:
        lines.append(f"[{item.id}] {item.text}")
    return "\n".join(lines)


def run_suite(
    *,
    provider: Provider,
    config: EvalKitConfig,
    cases: list[EvalCase],
    suite: str,
) -> RunRecord:
    """Run one suite's cases in order and produce the RunRecord."""
    started = datetime.now(timezone.utc)
    start_time_utc = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    clock_start = perf_counter()

    results: list[CaseResult] = []
    statuses: list[str] = []
    weights: list[tuple[float, bool, bool]] = []

    for case in cases:
        result = _run_single_case(provider=provider, config=config, case=case)
        results.append(result)
        statuses.append(result.status)
        if result.status != "error":
            case_weight = sum(rule.weight for rule in case.scoring)
            weights.append((case_weight, result.passed, result.needs_human))

    duration_ms = (perf_counter() - clock_start) * 1000.0
    summary = run_summary(statuses, weights, duration_ms)

    return RunRecord(
        run_id="",  # assigned by the store on save
        timestamp_utc=start_time_utc,
        evalkit_version=__version__,
        provider=config.provider,
        model=config.model or provider.name,
        config=config.snapshot(
            suites=[suite],
            evalkit_version=__version__,
            start_time_utc=start_time_utc,
        ),
        results=results,
        summary=summary,
        duration_ms=duration_ms,
    )


def _run_single_case(*, provider: Provider, config: EvalKitConfig, case: EvalCase) -> CaseResult:
    try:
        generation = provider.generate(_build_prompt(case))
    except ProviderError as exc:
        return CaseResult.from_outcome(
            case_id=case.case_id,
            suite=case.suite,
            score=None,
            error=f"{type(exc).__name__}: {exc}",
        )
    score, _weight = score_case(case, generation.text)
    return CaseResult.from_outcome(
        case_id=case.case_id,
        suite=case.suite,
        score=score,
        generation=generation,
    )


def run_cases(
    *,
    provider: Provider,
    config: EvalKitConfig,
    suites: dict[str, list[EvalCase]],
) -> RunRecord:
    """Multi-suite variant: run every case of every suite (storage and
    reports are suite-agnostic via CaseResult.suite)."""
    started = datetime.now(timezone.utc)
    start_time_utc = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    clock_start = perf_counter()

    results: list[CaseResult] = []
    statuses: list[str] = []
    weights: list[tuple[float, bool, bool]] = []

    for suite, cases in suites.items():
        for case in cases:
            result = _run_single_case(provider=provider, config=config, case=case)
            results.append(result)
            statuses.append(result.status)
            if result.status != "error":
                case_weight = sum(rule.weight for rule in case.scoring)
                weights.append((case_weight, result.passed, result.needs_human))

    duration_ms = (perf_counter() - clock_start) * 1000.0
    summary = run_summary(statuses, weights, duration_ms)

    return RunRecord(
        run_id="",
        timestamp_utc=start_time_utc,
        evalkit_version=__version__,
        provider=config.provider,
        model=config.model or provider.name,
        config=config.snapshot(
            suites=sorted(suites),
            evalkit_version=__version__,
            start_time_utc=start_time_utc,
        ),
        results=results,
        summary=summary,
        duration_ms=duration_ms,
    )