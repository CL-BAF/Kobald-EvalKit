"""Run-vs-run comparison (R5): never silently compare mismatched runs.

Two runs are comparable iff their config snapshots match on provider,
model, base_url, options and suite set, and their schema generations are
compatible (evalkit_version major.minor). Compare reports per-case status
pairs and summary deltas; incompatible runs raise CompareError naming
the mismatch.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import CompareError
from .models import RunRecord

__all__ = ["ComparisonCase", "Comparison", "compare_runs"]


@dataclass(frozen=True)
class ComparisonCase:
    case_id: str
    suite: str
    status_a: str
    status_b: str
    changed: bool


@dataclass(frozen=True)
class Comparison:
    run_id_a: str
    run_id_b: str
    comparable: bool
    summary_delta: dict
    cases: list[ComparisonCase]


_COMPARE_CONFIG_KEYS = ("provider", "model", "base_url", "options")


def _check_comparable(a: RunRecord, b: RunRecord) -> None:
    for key in _COMPARE_CONFIG_KEYS:
        if a.config.get(key) != b.config.get(key):
            raise CompareError(
                f"runs {a.run_id} and {b.run_id} differ in config.{key} "
                f"({a.config.get(key)!r} vs {b.config.get(key)!r}); "
                "refusing to compare mismatched runs"
            )
    suites_a = set(a.config.get("suites", []))
    suites_b = set(b.config.get("suites", []))
    if suites_a != suites_b:
        raise CompareError(
            f"runs {a.run_id} and {b.run_id} cover different suites "
            f"({sorted(suites_a)} vs {sorted(suites_b)}); refusing to compare"
        )
    if a.evalkit_version.rpartition(".")[0] != b.evalkit_version.rpartition(".")[0]:
        raise CompareError(
            f"runs were produced by different EvalKit generations "
            f"({a.evalkit_version} vs {b.evalkit_version}); refusing to compare"
        )


def compare_runs(a: RunRecord, b: RunRecord) -> Comparison:
    """Compare two persisted runs; raises CompareError on mismatch."""
    _check_comparable(a, b)

    by_id_a = {r.case_id: r for r in a.results}
    by_id_b = {r.case_id: r for r in b.results}
    all_ids = sorted(set(by_id_a) | set(by_id_b))
    cases: list[ComparisonCase] = []
    for case_id in all_ids:
        ra = by_id_a.get(case_id)
        rb = by_id_b.get(case_id)
        status_a = ra.status if ra else "missing"
        status_b = rb.status if rb else "missing"
        cases.append(
            ComparisonCase(
                case_id=case_id,
                suite=(ra or rb).suite,
                status_a=status_a,
                status_b=status_b,
                changed=status_a != status_b,
            )
        )

    summary_keys = (
        "total_cases",
        "passed",
        "failed",
        "needs_human",
        "errors",
    )
    summary_delta = {
        key: {"a": a.summary.get(key, 0), "b": b.summary.get(key, 0)}
        for key in summary_keys
        if a.summary.get(key, 0) != b.summary.get(key, 0)
    }
    rate_a = a.summary.get("weighted_pass_rate")
    rate_b = b.summary.get("weighted_pass_rate")
    if rate_a != rate_b:
        summary_delta["weighted_pass_rate"] = {"a": rate_a, "b": rate_b}
    return Comparison(
        run_id_a=a.run_id,
        run_id_b=b.run_id,
        comparable=True,
        summary_delta=summary_delta,
        cases=cases,
    )