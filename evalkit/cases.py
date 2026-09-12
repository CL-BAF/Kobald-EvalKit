"""Case loading and validation.

Normative schema: docs/case-schema.json (schema v1). Loader rules pinned
by Amendments v0.1.2/v0.1.3/v0.1.7 and Lead's M1 routing:

- one case per file at suites/<suite>/<case_id>.json; filename stem MUST
  equal case_id (mismatch rejected);
- the `suite` field must match the parent directory name and the
  directory must be in the v0.1 suite registry;
- optional suites/<suite>/suite.json is informational only — never a
  scoring source (loader ignores its content);
- unknown top-level keys are STRICTLY rejected (typo safety);
- schema_version optional, only "1" accepted in v0.1;
- weight optional float, default 1.0, values outside 0.5-5 rejected;
- scoring is 1-8 items of registered scorer types with dict params;
- duplicate case_id across files is rejected, naming BOTH files;
- `expected` is documentation-only and never read for scoring.

Loader failures raise CaseLoadError with messages that name the offending
file; the CLI aborts the run with exit 1 on any CaseLoadError.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import CaseLoadError

__all__ = [
    "SUITES_REGISTRY",
    "EvidenceItem",
    "ScoringRule",
    "EvalCase",
    "discover_suites",
    "load_suite",
    "load_cases",
    "load_case_file",
]

SUITES_REGISTRY = (
    "evidence_grounding",
    "contradiction",
    "fabricated_citations",
    "structured_output",
    "uncertainty",
    "mixed_evidence",
)

_CASE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SUITE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_EVIDENCE_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,23}$")

_TOP_LEVEL_KEYS = (
    "schema_version",
    "case_id",
    "suite",
    "title",
    "purpose",
    "evidence",
    "instruction",
    "constraints",
    "scoring",
    "expected",
)
_EVIDENCE_KEYS = ("id", "text")
_SCORING_KEYS = ("type", "params", "weight")
_WEIGHT_MIN, _WEIGHT_MAX = 0.5, 5.0

_CASE_TEXT_LIMITS = {
    "title": (1, 200),
    "purpose": (1, 2000),
    "instruction": (1, 6000),
    "constraints": (1, 2000),
    "expected": (1, 2000),
}


@dataclass(frozen=True)
class EvidenceItem:
    """One evidence source available to the model."""

    id: str
    text: str


@dataclass(frozen=True)
class ScoringRule:
    """One registered scorer invocation with its enforcement params."""

    type: str
    params: dict
    weight: float = 1.0


@dataclass(frozen=True)
class EvalCase:
    """A validated evaluation case (schema v1)."""

    schema_version: str
    case_id: str
    suite: str
    title: str
    purpose: str
    evidence: list[EvidenceItem]
    instruction: str
    constraints: str
    scoring: list[ScoringRule]
    expected: str
    source_file: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def evidence_ids(self) -> list[str]:
        return [item.id for item in self.evidence]


def _reject(path: Path, message: str) -> "CaseLoadError":
    return CaseLoadError(f"{path}: {message}")


def _check_text_field(path: Path, data: dict, key: str) -> str:
    value = data[key]
    low, high = _CASE_TEXT_LIMITS[key]
    if not isinstance(value, str):
        raise _reject(path, f"{key!r} must be a string")
    if not low <= len(value) <= high:
        raise _reject(path, f"{key!r} must be {low}-{high} chars, got {len(value)}")
    return value


def _load_scoring(path: Path, data: dict, known_types: set[str]) -> list[ScoringRule]:
    from .scoring import is_registered_scorer

    raw = data["scoring"]
    if not isinstance(raw, list):
        raise _reject(path, "'scoring' must be a list")
    if not 1 <= len(raw) <= 8:
        raise _reject(path, f"'scoring' must contain 1-8 items, got {len(raw)}")
    rules: list[ScoringRule] = []
    for index, entry in enumerate(raw):
        where = f"scoring[{index}]"
        if not isinstance(entry, dict):
            raise _reject(path, f"{where} must be an object")
        unknown = set(entry) - set(_SCORING_KEYS)
        if unknown:
            raise _reject(path, f"{where}: unknown key(s) {sorted(unknown)}")
        if "type" not in entry:
            raise _reject(path, f"{where}: missing 'type'")
        if "params" not in entry:
            raise _reject(path, f"{where}: missing 'params'")
        scorer_type = entry["type"]
        if not isinstance(scorer_type, str):
            raise _reject(path, f"{where}: 'type' must be a string")
        if not is_registered_scorer(scorer_type):
            raise _reject(
                path,
                f"{where}: unknown scoring type {scorer_type!r} "
                f"(registered: {sorted(known_types)})",
            )
        params = entry["params"]
        if not isinstance(params, dict):
            raise _reject(path, f"{where}: 'params' must be an object")
        weight = entry.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise _reject(path, f"{where}: 'weight' must be a number")
        if not _WEIGHT_MIN <= weight <= _WEIGHT_MAX:
            raise _reject(
                path,
                f"{where}: 'weight' must be between {_WEIGHT_MIN} and {_WEIGHT_MAX}, "
                f"got {weight}",
            )
        rules.append(ScoringRule(type=scorer_type, params=dict(params), weight=float(weight)))
    return rules


def _load_evidence(path: Path, data: dict) -> list[EvidenceItem]:
    raw = data["evidence"]
    if not isinstance(raw, list):
        raise _reject(path, "'evidence' must be a list")
    if len(raw) > 12:
        raise _reject(path, f"'evidence' allows at most 12 items, got {len(raw)}")
    items: list[EvidenceItem] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"evidence[{index}]"
        if not isinstance(entry, dict):
            raise _reject(path, f"{where} must be an object with 'id' and 'text'")
        unknown = set(entry) - set(_EVIDENCE_KEYS)
        if unknown:
            raise _reject(path, f"{where}: unknown key(s) {sorted(unknown)}")
        if "id" not in entry or "text" not in entry:
            raise _reject(path, f"{where}: requires both 'id' and 'text'")
        ev_id = entry["id"]
        text = entry["text"]
        if not isinstance(ev_id, str) or not _EVIDENCE_ID_RE.match(ev_id):
            raise _reject(
                path,
                f"{where}.id must match ^[A-Z0-9][A-Z0-9-]{{1,23}}$, got {ev_id!r}",
            )
        if ev_id in seen:
            raise _reject(path, f"{where}.id duplicates evidence id {ev_id!r}")
        if not isinstance(text, str) or not 1 <= len(text) <= 4000:
            raise _reject(path, f"{where}.text must be 1-4000 chars")
        seen.add(ev_id)
        items.append(EvidenceItem(id=ev_id, text=text))
    return items


def load_case_file(
    path: Path,
    *,
    scorer_types: set[str] | None = None,
) -> EvalCase:
    """Validate and load one case JSON file."""
    from .scoring import registered_scorer_names

    known = scorer_types if scorer_types is not None else set(registered_scorer_names())

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise _reject(path, f"cannot read file ({exc})") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _reject(path, f"invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise _reject(path, "top level must be a JSON object")

    unknown = set(data) - set(_TOP_LEVEL_KEYS)
    if unknown:
        raise _reject(path, f"unknown top-level key(s) {sorted(unknown)}")

    schema_version = data.get("schema_version", "1")
    if schema_version != "1":
        raise _reject(
            path,
            f"unsupported schema_version {schema_version!r} (only \"1\" in v0.1)",
        )

    for key in (
        "case_id",
        "suite",
        "title",
        "purpose",
        "evidence",
        "instruction",
        "constraints",
        "scoring",
        "expected",
    ):
        if key not in data:
            raise _reject(path, f"missing required key {key!r}")

    case_id = data["case_id"]
    if not isinstance(case_id, str) or not _CASE_ID_RE.match(case_id):
        raise _reject(
            path,
            f"case_id must match ^[a-z][a-z0-9_]{{0,63}}$ (safe filename charset), "
            f"got {case_id!r}",
        )
    stem = path.stem
    if stem != case_id:
        raise _reject(path, f"filename stem {stem!r} must equal case_id {case_id!r}")

    suite = data["suite"]
    if not isinstance(suite, str) or not _SUITE_RE.match(suite):
        raise _reject(path, f"suite must match ^[a-z][a-z0-9_]*$, got {suite!r}")
    if suite not in SUITES_REGISTRY:
        raise _reject(
            path,
            f"suite {suite!r} is not in the v0.1 registry {list(SUITES_REGISTRY)}",
        )
    parent = path.parent.name
    if suite != parent:
        raise _reject(path, f"suite {suite!r} must match parent directory {parent!r}")

    for key in _CASE_TEXT_LIMITS:
        _check_text_field(path, data, key)

    evidence = _load_evidence(path, data)
    scoring = _load_scoring(path, data, known)

    return EvalCase(
        schema_version=schema_version,
        case_id=case_id,
        suite=suite,
        title=data["title"],
        purpose=data["purpose"],
        evidence=evidence,
        instruction=data["instruction"],
        constraints=data["constraints"],
        scoring=scoring,
        expected=data["expected"],
        source_file=str(path),
    )


def load_cases(suites_dir: Path, suites: list[str]) -> dict[str, list[EvalCase]]:
    """Load several suites; returns {suite: [cases]} in given order."""
    return {suite: load_suite(suites_dir, suite) for suite in suites}


def discover_suites(suites_dir: Path) -> list[str]:
    """Registry suites that exist under suites_dir (sorted)."""
    if not suites_dir.is_dir():
        raise CaseLoadError(f"{suites_dir}: suites directory not found")
    found = [
        name
        for name in SUITES_REGISTRY
        if (suites_dir / name).is_dir()
        and any((suites_dir / name).glob("*.json"))
    ]
    return sorted(found)


def load_suite(suites_dir: Path, suite: str) -> list[EvalCase]:
    """Load every valid case file of one suite.

    Duplicate case_id across files is rejected naming both files. The
    informational suite.json is skipped.
    """
    if suite not in SUITES_REGISTRY:
        raise CaseLoadError(
            f"{suites_dir / suite}: suite {suite!r} is not in the v0.1 registry "
            f"{list(SUITES_REGISTRY)}"
        )
    suite_dir = suites_dir / suite
    if not suite_dir.is_dir():
        raise CaseLoadError(f"{suite_dir}: suite directory not found")
    by_id: dict[str, Path] = {}
    cases: list[EvalCase] = []
    for path in sorted(suite_dir.glob("*.json")):
        if path.name == "suite.json":
            continue
        case = load_case_file(path)
        if case.case_id in by_id:
            raise CaseLoadError(
                f"duplicate case_id {case.case_id!r} in files "
                f"{by_id[case.case_id]} and {path}"
            )
        by_id[case.case_id] = path
        cases.append(case)
    if not cases:
        raise CaseLoadError(f"{suite_dir}: no case files found")
    return cases