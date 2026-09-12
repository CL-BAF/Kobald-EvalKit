"""Structured-output, uncertainty, contradiction and fabricated-citation
scorers (marker-based rules; semantic judgement stays needs_human).

Spec: docs/scoring.md. These scorers never read `expected` or
`constraints`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..models import Check
from ..cases import EvalCase
from . import register_scorer

__all__ = []

_JSON_TYPE_NAMES = ("string", "number", "boolean", "array", "object")
_MAX_NAMED = 5


def _extract_first_json(response: str) -> tuple[Any, str] | tuple[None, str]:
    """First-position-only extraction (Reviewer pin): find the FIRST { or [
    in the response and raw_decode from that index ONLY; failure = fail.
    No try-each-position leniency."""
    positions = [(response.find("{"), "{"), (response.find("["), "[")]
    candidates = [(i, o) for i, o in positions if i != -1]
    if not candidates:
        return None, "no JSON object or array found in response"
    index, opener = min(candidates)
    try:
        value, _ = json.JSONDecoder().raw_decode(response[index:])
        return value, ""
    except json.JSONDecodeError as exc:
        return None, f"JSON parse error after {opener!r} at offset {index}: {exc.msg}"


def _valid_json(case: EvalCase, response: str, params: dict) -> list[Check]:
    value, reason = _extract_first_json(response)
    return [
        Check(
            name="valid_json",
            passed=value is not None,
            detail="first JSON value parsed" if value is not None else reason,
        )
    ]


def _required_fields(case: EvalCase, response: str, params: dict) -> list[Check]:
    fields = params.get("fields")
    if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
        raise ValueError("required_fields: 'fields' must be a list of strings")
    strict = params.get("strict", False)
    if not isinstance(strict, bool):
        raise ValueError("required_fields: 'strict' must be a bool")
    value, reason = _extract_first_json(response)
    if value is None:
        return [
            Check(
                name="required_fields",
                passed=False,
                detail=f"cannot check fields: {reason}",
                needs_human=False,
            )
        ]
    if not isinstance(value, dict):
        return [
            Check(
                name="required_fields",
                passed=False,
                detail=f"extracted JSON is {type(value).__name__}, not an object",
            )
        ]
    missing = [f for f in fields if f not in value or value[f] is None]
    extras = sorted(set(value) - set(fields)) if strict else []
    passed = not missing and not extras
    if missing:
        detail = f"missing/null field(s): {', '.join(missing)}"
    elif extras:
        detail = f"extra top-level key(s) under strict: {', '.join(extras)}"
    else:
        detail = f"all {len(fields)} required field(s) present"
    return [Check(name="required_fields", passed=passed, detail=detail, count=len(missing))]


def _field_type(case: EvalCase, response: str, params: dict) -> list[Check]:
    field_name = params.get("field")
    if not isinstance(field_name, str) or not field_name:
        raise ValueError("field_type: 'field' must be a non-empty string")
    expected_type = params.get("type")
    if expected_type not in _JSON_TYPE_NAMES:
        raise ValueError(
            f"field_type: 'type' must be one of {_JSON_TYPE_NAMES}, got {expected_type!r}"
        )
    value, reason = _extract_first_json(response)
    if value is None:
        return [
            Check(name="field_type", passed=False, detail=f"cannot check type: {reason}")
        ]
    if not isinstance(value, dict) or field_name not in value:
        return [
            Check(
                name="field_type",
                passed=False,
                detail=(
                    f"field {field_name!r} absent in extracted JSON"
                    if isinstance(value, dict)
                    else "extracted JSON is not an object"
                ),
            )
        ]
    actual = value[field_name]
    matches = {
        "string": isinstance(actual, str),
        "number": isinstance(actual, (int, float)) and not isinstance(actual, bool),
        "boolean": isinstance(actual, bool),
        "array": isinstance(actual, list),
        "object": isinstance(actual, dict),
    }[expected_type]
    return [
        Check(
            name="field_type",
            passed=matches,
            detail=(
                f"field {field_name!r} is {type(actual).__name__}, expected {expected_type}"
                if not matches
                else f"field {field_name!r} is {expected_type}"
            ),
        )
    ]


def _uncertainty_expression(case: EvalCase, response: str, params: dict) -> list[Check]:
    min_hedges = params.get("min_hedges")
    if isinstance(min_hedges, bool) or not isinstance(min_hedges, int):
        raise ValueError("uncertainty_expression: 'min_hedges' must be an integer")
    hedges = params.get("hedges", [])
    if not isinstance(hedges, list) or not all(isinstance(h, str) for h in hedges):
        raise ValueError("uncertainty_expression: 'hedges' must be a list of strings")
    disallowed = params.get("disallowed", [])
    if not isinstance(disallowed, list) or not all(isinstance(d, str) for d in disallowed):
        raise ValueError("uncertainty_expression: 'disallowed' must be a list of strings")
    low = response.lower()
    hedge_count = sum(low.count(h.lower()) for h in hedges)
    overconfident = sum(low.count(d.lower()) for d in disallowed)
    passed = hedge_count >= min_hedges and overconfident == 0
    if overconfident:
        detail = (
            f"{hedge_count} hedge phrase(s) (min {min_hedges}) but "
            f"{overconfident} overconfident phrase(s) present"
        )
    else:
        detail = f"{hedge_count} hedge phrase(s) found (min required {min_hedges})"
    return [
        Check(
            name="uncertainty_expression",
            passed=passed,
            detail=detail,
            count=hedge_count,
        )
    ]


def _lexical_contradiction(case: EvalCase, response: str, params: dict) -> list[Check]:
    """Rule-based self-contradiction: response asserting both members of a
    case-provided pair fails. String-keyed lookup, not NLI.

    params: {"pairs": [[claim_a, claim_b], ...]} — each pair is two
    phrases (case-insensitive) that must not BOTH appear in the response.
    """
    pairs = params.get("pairs")
    if not isinstance(pairs, list) or not all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(s, str) for s in p)
        for p in pairs
    ):
        raise ValueError(
            "lexical_contradiction: 'pairs' must be a list of [string, string] pairs"
        )
    low = response.lower()
    contradicted: list[list[str]] = []
    for pair in pairs:
        a, b = pair
        if a.lower() in low and b.lower() in low:
            contradicted.append([a, b])
    count = len(contradicted)
    detail = (
        "both members asserted for pair(s): "
        + "; ".join(f"{a!r} / {b!r}" for a, b in contradicted)
        if count
        else "no contradictory pair asserted"
    )
    return [Check(name="lexical_contradiction", passed=count == 0, detail=detail, count=count)]


def _all_sources_present(case: EvalCase, response: str, params: dict) -> list[Check]:
    """Every evidence ID of the case must appear as a citation token."""
    from . import CITATION_TOKEN_RE

    ids = case.evidence_ids
    found = {t[1:-1] for t in CITATION_TOKEN_RE.findall(response)}
    missing = [i for i in ids if i not in found]
    passed = not missing
    detail = (
        f"missing citation(s) for: {', '.join(missing)}"
        if missing
        else f"all {len(ids)} evidence id(s) cited"
    )
    return [Check(name="all_sources_present", passed=passed, detail=detail, count=len(missing))]


def _unresolved_marker(case: EvalCase, response: str, params: dict) -> list[Check]:
    """Response must not leave unresolved placeholder markers behind."""
    patterns = params.get("patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ValueError("unresolved_marker: 'patterns' must be a list of regex strings")
    default_patterns = [r"<[A-Z_]+>", r"\{\{[A-Za-z_]+\}\}", r"TODO"]
    patterns = patterns or default_patterns
    found: list[str] = []
    for pattern in patterns:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"unresolved_marker: bad pattern {pattern!r}: {exc}") from exc
        found.extend(m.group(0) for m in compiled.finditer(response))
    count = len(found)
    detail = (
        f"unresolved placeholder(s) left in response: {', '.join(sorted(set(found)))}"
        if count
        else "no unresolved placeholders"
    )
    return [Check(name="unresolved_marker", passed=count == 0, detail=detail, count=count)]


def _no_absolute_claims(case: EvalCase, response: str, params: dict) -> list[Check]:
    """Uncertainty posture: absolute-confidence phrases must not appear."""
    phrases = params.get("phrases", ["definitely", "certainly", "obviously"])
    if not isinstance(phrases, list) or not all(isinstance(p, str) for p in phrases):
        raise ValueError("no_absolute_claims: 'phrases' must be a list of strings")
    allow_needs_human = params.get("needs_human", False)
    if not isinstance(allow_needs_human, bool):
        raise ValueError("no_absolute_claims: 'needs_human' must be a bool")
    low = response.lower()
    hits = sum(low.count(p.lower()) for p in phrases)
    detail = (
        f"{hits} absolute-confidence phrase(s) present"
        if hits
        else "no absolute-confidence phrases"
    )
    return [
        Check(
            name="no_absolute_claims",
            passed=hits == 0,
            detail=detail,
            count=hits,
            needs_human=allow_needs_human and hits > 0,
        )
    ]


def _conflict_assessment(case: EvalCase, response: str, params: dict) -> list[Check]:
    """Always needs_human: weighing conflicting evidence is semantic
    judgement EvalKit refuses to fake in v0.1. The check reports
    passed=False ('not verified by automation') without failing the case
    silently; the case becomes needs_human."""
    instructions = params.get("instructions")
    detail = (
        str(instructions)
        if isinstance(instructions, str) and instructions
        else "human must judge how the response resolves the conflicting evidence "
        "(accuracy of weighing, not just presence of hedges)"
    )
    return [
        Check(
            name="conflict_assessment",
            passed=False,
            detail=detail,
            needs_human=True,
        )
    ]


def _insufficiency_marker(case: EvalCase, response: str, params: dict) -> list[Check]:
    """Insufficiency-marker scoring (Amendment v0.1.11): verifies the model
    flags missing figures with an exact marker phrase.

    params: {"marker": str (required), "min_marker_count": int (default 1),
    "max_marker_count": int | None (default None = unbounded),
    "forbidden_patterns": [regex strings], "marker_in_quotes": bool
    (default true — marker matched as a quoted literal substring)}.

    Passes iff: marker count (case-insensitive substring search) is within
    [min_marker_count, max_marker_count] (None = unbounded), no
    forbidden_pattern matches, and no citation-like token outside the
    case's evidence ID set appears. needs_human: no. The max bound enables
    discrimination pairs (marker required when the evidence lacks a
    figure, forbidden when it has one). Honesty limit: marker compliance
    is not calibrated confidence — that judgement stays human.
    """
    marker = params.get("marker")
    if not isinstance(marker, str) or not marker:
        raise ValueError("insufficiency_marker: 'marker' must be a non-empty string")
    min_count = params.get("min_marker_count", 1)
    if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 0:
        raise ValueError("insufficiency_marker: 'min_marker_count' must be a non-negative integer")
    max_count = params.get("max_marker_count")
    if max_count is not None and (
        isinstance(max_count, bool) or not isinstance(max_count, int) or max_count < 0
    ):
        raise ValueError("insufficiency_marker: 'max_marker_count' must be a non-negative integer or null")
    if max_count is not None and min_count > max_count:
        raise ValueError(
            f"insufficiency_marker: min_marker_count {min_count} > max_marker_count {max_count}"
        )
    forbidden = params.get("forbidden_patterns", [])
    if not isinstance(forbidden, list) or not all(isinstance(p, str) for p in forbidden):
        raise ValueError("insufficiency_marker: 'forbidden_patterns' must be a list of regex strings")
    in_quotes = params.get("marker_in_quotes", True)
    if not isinstance(in_quotes, bool):
        raise ValueError("insufficiency_marker: 'marker_in_quotes' must be a bool")

    needle = f'"{marker}"' if in_quotes else marker
    low = response.lower()
    count = 0
    start = 0
    while True:
        index = low.find(needle.lower(), start)
        if index == -1:
            break
        count += 1
        start = index + len(needle)

    forbidden_hits: list[str] = []
    for pattern in forbidden:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"insufficiency_marker: bad pattern {pattern!r}: {exc}") from exc
        forbidden_hits.extend(m.group(0) for m in compiled.finditer(response))

    from . import CITATION_TOKEN_RE

    evidence_ids = set(case.evidence_ids)
    invented = [
        t[1:-1] for t in CITATION_TOKEN_RE.findall(response) if t[1:-1] not in evidence_ids
    ]

    problems: list[str] = []
    if count < min_count:
        problems.append(f"marker {needle} found {count} time(s), requires >= {min_count}")
    if max_count is not None and count > max_count:
        problems.append(f"marker {needle} found {count} time(s), allows <= {max_count}")
    if forbidden_hits:
        shown = ", ".join(sorted(set(forbidden_hits))[:_MAX_NAMED])
        problems.append(f"forbidden pattern(s) present: {shown}")
    if invented:
        shown = ", ".join(f"'[{i}]'" for i in sorted(set(invented))[:_MAX_NAMED])
        problems.append(f"citation-like token(s) not in evidence: {shown}")

    passed = not problems
    detail = (
        "; ".join(problems)
        if problems
        else f"marker {needle} present {count} time(s) (allowed {min_count}-"
        + (str(max_count) if max_count is not None else "unbounded")
        + "), no forbidden patterns, no invented citations"
    )
    return [
        Check(
            name="insufficiency_marker",
            passed=passed,
            detail=detail,
            count=count,
        )
    ]


register_scorer("valid_json", _valid_json)
register_scorer("required_fields", _required_fields)
register_scorer("field_type", _field_type)
register_scorer("uncertainty_expression", _uncertainty_expression)
register_scorer("lexical_contradiction", _lexical_contradiction)
register_scorer("all_sources_present", _all_sources_present)
register_scorer("unresolved_marker", _unresolved_marker)
register_scorer("no_absolute_claims", _no_absolute_claims)
register_scorer("conflict_assessment", _conflict_assessment)
register_scorer("insufficiency_marker", _insufficiency_marker)