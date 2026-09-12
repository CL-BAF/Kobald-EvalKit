"""Deterministic scoring engine.

Semantics pinned by contract (R4, v0.1.3 A2/A4, v0.1.7 #1):

- A Check has name, passed, detail, optional count, optional needs_human.
- A needs_human check reports passed=False meaning "not verified by
  automation"; it never silently passes and never silently fails a case.
- ScoreResult.passed = every NON-needs_human check passed.
- ScoreResult.needs_human = ANY check has needs_human=True.
- CaseResult.passed = ScoreResult.passed AND NOT needs_human.
- Weights are used ONLY for the reported aggregate, NEVER for pass/fail.

Aggregate formula (also printed in reports):

    weighted_pass_rate = sum(weights of passed cases)
                       / sum(weights of all scored cases)

averaged over NON-needs_human cases only; cases needing human review are
listed separately and never averaged in. Limitations: (1) weights are
ordinal design choices, not measured importance; (2) cases are small
behavioural probes, not a representative sample of any population;
(3) rates from different model sizes, quantisations or option sets are
not comparable unless the user controls those variables. No overall
"score" number is published.

Normative scorer spec: docs/scoring.md. Citation-token regex:
``\\[[A-Z0-9][A-Z0-9-]{1,23}\\]``.
"""

from __future__ import annotations

import re
from typing import Callable

from ..errors import ScoringError
from ..models import Check, ScoreResult
from ..cases import EvalCase

__all__ = [
    "CITATION_TOKEN_RE",
    "AGGREGATE_FORMULA",
    "AGGREGATE_LIMITATIONS",
    "ScorerFunc",
    "SCORERS",
    "register_scorer",
    "is_registered_scorer",
    "registered_scorer_names",
    "score_case",
    "weighted_pass_rate",
    "run_summary",
]

AGGREGATE_FORMULA = (
    "weighted_pass_rate = sum(weights of passed cases) / "
    "sum(weights of all scored cases), over non-needs_human cases only"
)
AGGREGATE_LIMITATIONS = (
    "weights are ordinal design choices, not measured importance",
    "cases are small behavioural probes, not a representative sample of any population",
    "rates from different model sizes, quantisations or option sets are not "
    "comparable unless the user controls those variables",
)

CITATION_TOKEN_RE = re.compile(r"\[[A-Z0-9][A-Z0-9-]{1,23}\]")

ScorerFunc = Callable[[EvalCase, str, dict], list[Check]]

SCORERS: dict[str, ScorerFunc] = {}


def register_scorer(name: str, func: ScorerFunc) -> None:
    if name in SCORERS:
        raise ScoringError(f"scorer {name!r} already registered")
    SCORERS[name] = func


def is_registered_scorer(name: str) -> bool:
    _load_builtin_scorers()
    return name in SCORERS


def registered_scorer_names() -> set[str]:
    _load_builtin_scorers()
    return set(SCORERS)


def score_case(case: EvalCase, response_text: str) -> tuple[ScoreResult, float]:
    """Score one response against one case.

    Returns (ScoreResult, weight_sum) where weight_sum is the case's
    total weight (weights never influence pass/fail). Unknown scorer
    types cannot reach this point: the loader rejects them.
    """
    checks: list[Check] = []
    weight_sum = 0.0
    _load_builtin_scorers()
    for rule in case.scoring:
        scorer = SCORERS.get(rule.type)
        if scorer is None:
            raise ScoringError(
                f"case {case.case_id}: unknown scoring type {rule.type!r}"
            )
        produced = scorer(case, response_text, dict(rule.params))
        if not produced:
            raise ScoringError(
                f"case {case.case_id}: scorer {rule.type!r} produced no checks"
            )
        checks.extend(produced)
        weight_sum += rule.weight
    return ScoreResult.from_checks(checks), weight_sum


def weighted_pass_rate(rates: list[tuple[float, bool, bool]]) -> float | None:
    """Aggregate over (weight, passed, needs_human) triples.

    Non-needs_human cases only; returns None when nothing is scoreable.
    """
    total = sum(w for w, _, nh in rates if not nh)
    passed = sum(w for w, p, nh in rates if not nh and p)
    if total <= 0:
        return None
    return passed / total


def run_summary(
    statuses: list[str],
    weights: list[tuple[float, bool, bool]],
    duration_ms: float,
) -> dict:
    """Build the mandatory-six summary plus the documented aggregate.

    Mandatory keys: total_cases, passed, failed, needs_human, errors,
    duration_ms. Extras: weighted_pass_rate (None when no scoreable
    cases), needs_human_case_ids placeholder filled by caller if needed.
    """
    passed = sum(1 for s in statuses if s == "passed")
    failed = sum(1 for s in statuses if s == "failed")
    needs_human = sum(1 for s in statuses if s == "needs_human")
    errors = sum(1 for s in statuses if s == "error")
    summary = {
        "total_cases": len(statuses),
        "passed": passed,
        "failed": failed,
        "needs_human": needs_human,
        "errors": errors,
        "duration_ms": float(duration_ms),
    }
    rate = weighted_pass_rate(weights)
    if rate is not None:
        summary["weighted_pass_rate"] = round(rate, 4)
    return summary


def _load_builtin_scorers() -> None:
    """Import the built-in scorer modules so their registrations run.

    Called lazily by score_case/registered_scorer_names to avoid a
    circular import at package import time (scorer modules import back
    from this package).
    """
    from . import grounding, rules  # noqa: F401