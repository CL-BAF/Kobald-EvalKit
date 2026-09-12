"""Evidence-grounding scorers: required_source_ids, invented_citations,
unsupported_claims (marker-based, with its needs_human escape hatch).

Spec: docs/scoring.md. These scorers never read `expected` or
`constraints`; params are the only enforcement source.
"""

from __future__ import annotations

import re as _re

from ..models import Check
from ..cases import EvalCase
from . import CITATION_TOKEN_RE, register_scorer

__all__ = []

_DEFAULT_MIN_LENGTH = 200
_MAX_NAMED_MARKERS = 5
_MARKERS_NOTE = (
    "marker occurrences are counted case-insensitively; overlapping matches "
    "and multiple occurrences in one sentence each count"
)


def _tokens(text: str) -> list[str]:
    return CITATION_TOKEN_RE.findall(text)


def _strip_brackets(token: str) -> str:
    return token[1:-1]


def _required_source_ids(case: EvalCase, response: str, params: dict) -> list[Check]:
    ids = params.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("required_source_ids: 'ids' must be a list of strings")
    allow_extras = params.get("allow_extras", False)
    if not isinstance(allow_extras, bool):
        raise ValueError("required_source_ids: 'allow_extras' must be a bool")
    found = {_strip_brackets(t) for t in _tokens(response)}
    evidence_ids = set(case.evidence_ids)
    missing = [i for i in ids if i not in found]
    extras = sorted(found & evidence_ids - set(ids)) if not allow_extras else []
    passed = not missing and not extras
    if missing:
        detail = f"missing required citation(s): {', '.join(missing)}"
    elif extras:
        detail = f"cited non-required evidence id(s): {', '.join(extras)}"
    else:
        detail = f"all {len(ids)} required id(s) cited"
    return [
        Check(
            name="required_source_ids",
            passed=passed,
            detail=detail,
            count=len(missing),
        )
    ]


def _invented_citations(case: EvalCase, response: str, params: dict) -> list[Check]:
    max_allowed = params.get("max_allowed")
    if isinstance(max_allowed, bool) or not isinstance(max_allowed, int):
        raise ValueError("invented_citations: 'max_allowed' must be an integer")
    ids = params.get("ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("invented_citations: 'ids' must be a list of strings")
    patterns = params.get("patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
        raise ValueError("invented_citations: 'patterns' must be a list of regex strings")
    allowed = set(ids)
    invented: list[str] = []
    for token in _tokens(response):
        candidate = _strip_brackets(token)
        if candidate not in allowed:
            invented.append(candidate)
    for pattern in patterns:
        try:
            compiled = _re.compile(pattern)
        except _re.error as exc:
            raise ValueError(f"invented_citations: bad pattern {pattern!r}: {exc}") from exc
        invented.extend(match.group(0) for match in compiled.finditer(response))
    count = len(invented)
    named = ", ".join(f"'{token}'" for token in sorted(set(invented))[:_MAX_NAMED_MARKERS])
    if len(set(invented)) > _MAX_NAMED_MARKERS:
        named += f" and {len(set(invented)) - _MAX_NAMED_MARKERS} more"
    detail = (
        f"{count} invented citation(s) found: {named} (max allowed {max_allowed})"
        if count
        else "no invented citations"
    )
    return [
        Check(
            name="invented_citations",
            passed=count <= max_allowed,
            detail=detail,
            count=count,
        )
    ]


def _unsupported_claims(case: EvalCase, response: str, params: dict) -> list[Check]:
    """Marker-count algorithm per v0.1.10 ruling: counts occurrences of the
    case's declared failure markers (case-insensitive substring search;
    overlapping occurrences of the same marker each count; occurrences
    within one sentence still count). passed iff count <= max_allowed.
    The needs_human escape hatch is unchanged: zero citation tokens in a
    response >= min_length chars -> needs_human. Note: {_MARKERS_NOTE}"""
    max_allowed = params.get("max_allowed")
    if isinstance(max_allowed, bool) or not isinstance(max_allowed, int):
        raise ValueError("unsupported_claims: 'max_allowed' must be an integer")
    min_length = params.get("min_length", _DEFAULT_MIN_LENGTH)
    if isinstance(min_length, bool) or not isinstance(min_length, int) or min_length < 0:
        raise ValueError("unsupported_claims: 'min_length' must be a non-negative integer")
    markers = params.get("markers", [])
    if not isinstance(markers, list) or not all(isinstance(m, str) for m in markers):
        raise ValueError("unsupported_claims: 'markers' must be a list of strings")

    needs_human = False
    token_count = len(_tokens(response))
    if token_count == 0 and len(response) >= min_length:
        needs_human = True

    counts: dict[str, int] = {}
    low = response.lower()
    for marker in markers:
        needle = marker.lower()
        hits = 0
        start = 0
        while True:
            index = low.find(needle, start)
            if index == -1:
                break
            hits += 1
            start = index + len(needle)
        if hits:
            counts[marker] = hits
    claims = sum(counts.values())

    if needs_human:
        detail = (
            "needs human review: zero citation tokens in a "
            f"{len(response)}-char response; automation cannot verify grounding; "
            f"claim-marker count {claims} (max allowed {max_allowed})"
        )
    else:
        passed = claims <= max_allowed
        if claims:
            named = list(counts.items())
            shown = named[:_MAX_NAMED_MARKERS]
            label = ", ".join(f"'{marker}' x{hits}" for marker, hits in shown)
            if len(named) > _MAX_NAMED_MARKERS:
                label += f" and {len(named) - _MAX_NAMED_MARKERS} more marker type(s)"
            detail = (
                f"{claims} uncited claim marker(s): {label} "
                f"(max allowed {max_allowed})"
            )
        else:
            detail = "no uncited claim markers"
    return [
        Check(
            name="unsupported_claims",
            passed=False if needs_human else claims <= max_allowed,
            detail=detail,
            count=None if needs_human else claims,
            needs_human=needs_human,
        )
    ]


register_scorer("required_source_ids", _required_source_ids)
register_scorer("invented_citations", _invented_citations)
register_scorer("unsupported_claims", _unsupported_claims)