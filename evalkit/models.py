"""Result models for EvalKit runs.

Shapes are pinned by contract amendments v0.1.1-v0.1.9:

- Check: name/passed/detail/count/needs_human; a needs_human check reports
  passed=False meaning "not verified by automation" — it never silently
  passes and never silently fails a case.
- ScoreResult.passed = every NON-needs_human check passed;
  ScoreResult.needs_human = ANY check has needs_human=True.
- CaseResult.passed = ScoreResult.passed AND NOT ScoreResult.needs_human;
  status enum is exactly "passed" | "failed" | "needs_human" | "error"
  (derivation: generation failure -> "error"; score.needs_human ->
  "needs_human"; else passed/failed). Every started case appears in
  results, even error cases, so compare denominators stay stable.
- RunRecord carries no singular suite; suites live in the config snapshot
  and on each CaseResult. summary always contains the six mandatory keys
  total_cases, passed, failed, needs_human, errors, duration_ms
  (v0.1.3 A3) — construction and from_dict REJECT records missing any of
  them (loud boundary, no silent default rendering), extras like
  weighted_pass_rate are allowed.

Serialization round-trips through result.json exactly:
from_dict(to_dict(obj)) == obj for every model here.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from .provider.base import GenerationResult, ModelInfo

__all__ = [
    "GenerationResult",
    "ModelInfo",
    "CASE_STATUSES",
    "Check",
    "ScoreResult",
    "CaseResult",
    "RunRecord",
]

CASE_STATUSES = ("passed", "failed", "needs_human", "error")

MANDATORY_SUMMARY_KEYS = (
    "total_cases",
    "passed",
    "failed",
    "needs_human",
    "errors",
    "duration_ms",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class Check:
    """One scoring check outcome."""

    name: str
    passed: bool
    detail: str
    count: int | None = None
    needs_human: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "count": self.count,
            "needs_human": self.needs_human,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Check":
        _require(isinstance(data, dict), "check entry must be an object")
        for key in ("name", "passed", "detail"):
            _require(key in data, f"check missing required key {key!r}")
        _require(
            isinstance(data["name"], str) and isinstance(data["detail"], str),
            "check 'name' and 'detail' must be strings",
        )
        _require(isinstance(data["passed"], bool), "check 'passed' must be a bool")
        count = data.get("count")
        _require(count is None or isinstance(count, int), "check 'count' must be int or null")
        needs_human = data.get("needs_human", False)
        _require(isinstance(needs_human, bool), "check 'needs_human' must be a bool")
        return cls(
            name=data["name"],
            passed=data["passed"],
            detail=data["detail"],
            count=count,
            needs_human=needs_human,
        )


@dataclass(frozen=True)
class ScoreResult:
    """Outcome of scoring one response."""

    checks: list[Check] = field(default_factory=list)
    passed: bool = False
    needs_human: bool = False

    def to_dict(self) -> dict:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "passed": self.passed,
            "needs_human": self.needs_human,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScoreResult":
        _require(isinstance(data, dict), "score must be an object")
        checks_raw = data.get("checks")
        _require(isinstance(checks_raw, list), "score 'checks' must be a list")
        checks = [Check.from_dict(entry) for entry in checks_raw]
        _require(isinstance(data.get("passed"), bool), "score 'passed' must be a bool")
        _require(
            isinstance(data.get("needs_human"), bool), "score 'needs_human' must be a bool"
        )
        return cls(checks=checks, passed=data["passed"], needs_human=data["needs_human"])

    @classmethod
    def from_checks(cls, checks: list[Check]) -> "ScoreResult":
        """Derive passed/needs_human per the pinned semantics (v0.1.7 #1)."""
        decisive = [check for check in checks if not check.needs_human]
        return cls(
            checks=list(checks),
            passed=all(check.passed for check in decisive),
            needs_human=any(check.needs_human for check in checks),
        )


def _generation_to_dict(generation: GenerationResult) -> dict:
    return {
        "text": generation.text,
        "model": generation.model,
        "provider": generation.provider,
        "elapsed_ms": float(generation.elapsed_ms),
        "raw": dict(generation.raw),
    }


def _generation_from_dict(data: dict) -> GenerationResult:
    _require(isinstance(data, dict), "generation must be an object")
    for key in ("text", "model", "provider", "elapsed_ms"):
        _require(key in data, f"generation missing required key {key!r}")
    raw = data.get("raw")
    _require(raw is None or isinstance(raw, dict), "generation 'raw' must be an object")
    return GenerationResult(
        text=str(data["text"]),
        model=str(data["model"]),
        provider=str(data["provider"]),
        elapsed_ms=float(data["elapsed_ms"]),
        raw=dict(raw or {}),
    )


@dataclass(frozen=True)
class CaseResult:
    """One case's outcome inside a run.

    generation is None exactly when status == "error" (the case started
    but never produced a response); error is None on every non-error
    status.
    """

    case_id: str
    suite: str
    passed: bool
    needs_human: bool
    score: ScoreResult
    generation: GenerationResult | None
    error: str | None = None
    status: str = "failed"

    def __post_init__(self) -> None:
        _require(self.status in CASE_STATUSES, f"invalid status {self.status!r}")
        _require(
            (self.generation is None) == (self.status == "error"),
            "generation is None exactly for status 'error'",
        )
        _require(
            self.error is None or self.status == "error",
            "error is set only for status 'error'",
        )

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "suite": self.suite,
            "passed": self.passed,
            "needs_human": self.needs_human,
            "score": self.score.to_dict(),
            "generation": (
                _generation_to_dict(self.generation) if self.generation is not None else None
            ),
            "error": self.error,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CaseResult":
        _require(isinstance(data, dict), "case result must be an object")
        for key in ("case_id", "suite", "passed", "needs_human", "score", "status"):
            _require(key in data, f"case result missing required key {key!r}")
        score = ScoreResult.from_dict(data["score"])
        generation_raw = data.get("generation")
        generation = (
            _generation_from_dict(generation_raw) if generation_raw is not None else None
        )
        error = data.get("error")
        _require(error is None or isinstance(error, str), "case 'error' must be a string or null")
        status = data["status"]
        _require(status in CASE_STATUSES, f"invalid status {status!r}")
        return cls(
            case_id=str(data["case_id"]),
            suite=str(data["suite"]),
            passed=bool(data["passed"]),
            needs_human=bool(data["needs_human"]),
            score=score,
            generation=generation,
            error=error,
            status=status,
        )

    @classmethod
    def from_outcome(
        cls,
        *,
        case_id: str,
        suite: str,
        score: ScoreResult,
        generation: GenerationResult | None = None,
        error: str | None = None,
    ) -> "CaseResult":
        """Build a CaseResult applying the pinned status derivation."""
        if error is None and score is None:
            raise ValueError(
                "from_outcome requires either a score or an error; "
                "a case with neither is not a valid outcome"
            )
        if error is not None:
            return cls(
                case_id=case_id,
                suite=suite,
                passed=False,
                needs_human=False,
                score=ScoreResult(checks=[], passed=False, needs_human=False),
                generation=None,
                error=error,
                status="error",
            )
        passed = score.passed and not score.needs_human
        if score.needs_human:
            status = "needs_human"
        elif passed:
            status = "passed"
        else:
            status = "failed"
        return cls(
            case_id=case_id,
            suite=suite,
            passed=passed,
            needs_human=score.needs_human,
            score=score,
            generation=generation,
            error=None,
            status=status,
        )


@dataclass(frozen=True)
class RunRecord:
    """A complete evaluation run.

    config is the R5 snapshot: model, provider, base_url, options, suites,
    evalkit_version, start_time_utc. summary contains the six mandatory
    keys plus allowed extras (weighted_pass_rate, suite breakdown).
    """

    run_id: str
    timestamp_utc: str
    evalkit_version: str
    provider: str
    model: str
    config: dict
    results: list[CaseResult]
    summary: dict
    duration_ms: float

    def __post_init__(self) -> None:
        missing = [key for key in MANDATORY_SUMMARY_KEYS if key not in self.summary]
        if missing:
            raise ValueError(
                f"summary missing mandatory key(s) {missing} "
                f"(v0.1.3 A3: required keys are {list(MANDATORY_SUMMARY_KEYS)})"
            )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp_utc": self.timestamp_utc,
            "evalkit_version": self.evalkit_version,
            "provider": self.provider,
            "model": self.model,
            "config": dict(self.config),
            "results": [result.to_dict() for result in self.results],
            "summary": dict(self.summary),
            "duration_ms": float(self.duration_ms),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        _require(isinstance(data, dict), "run record must be an object")
        for key in (
            "run_id",
            "timestamp_utc",
            "evalkit_version",
            "provider",
            "model",
            "config",
            "results",
            "summary",
            "duration_ms",
        ):
            _require(key in data, f"run record missing required key {key!r}")
        _require(isinstance(data["config"], dict), "run 'config' must be an object")
        _require(isinstance(data["summary"], dict), "run 'summary' must be an object")
        missing_summary = [key for key in MANDATORY_SUMMARY_KEYS if key not in data["summary"]]
        if missing_summary:
            raise ValueError(
                f"summary missing mandatory key(s) {missing_summary} "
                f"(v0.1.3 A3: required keys are {list(MANDATORY_SUMMARY_KEYS)})"
            )
        results_raw = data["results"]
        _require(isinstance(results_raw, list), "run 'results' must be a list")
        results = [CaseResult.from_dict(entry) for entry in results_raw]
        return cls(
            run_id=str(data["run_id"]),
            timestamp_utc=str(data["timestamp_utc"]),
            evalkit_version=str(data["evalkit_version"]),
            provider=str(data["provider"]),
            model=str(data["model"]),
            config=dict(data["config"]),
            results=results,
            summary=dict(data["summary"]),
            duration_ms=float(data["duration_ms"]),
        )


def model_fields(model: Any) -> tuple[str, ...]:
    """Field names of a frozen dataclass model (helper for compare)."""
    return tuple(f.name for f in dataclasses.fields(model))