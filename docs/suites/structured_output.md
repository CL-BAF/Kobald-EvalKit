# Suite: structured_output — Design Note (M2)

Status: v0.1, owned by EvalDesign, aligned to contract amendments through
v0.1.11. Scorer implementations live in `evalkit/scoring/rules.py` (Core
implements; Tests verify against this spec).

## What this suite tests

Does the model emit machine-parseable output that matches an exact schema?

1. **One parseable document.** The response's first JSON-looking opener is
   the document; it must `raw_decode` (first-position-only, no fallback).
2. **Exact field contract.** Required fields present and non-null; strict
   mode rejects extras; per-element semantics when the value is an array.
3. **Correct types.** Numbers are numbers (not strings, not booleans).

## Why

Downstream tooling that parses model output mechanically breaks on prose
wrappers, trailing commentary, bonus fields, or string-typed numbers. These
cases measure that contract precisely; format failures are countable and
explainable (the detail names the reason).

## Scoring model (normative)

- `valid_json` (w3) — first-position extraction; failure states the offset
  and parse reason.
- `required_fields` (w4) — object-level or per-element array semantics
  (pinned G1: strict applies per element).
- `field_type` (w2) — JSON type of a named field, or the root with
  `{"field": "$"}` (pinned G2); `number` excludes booleans.

## Case roster (2 cases)

| case_id | tests | scoring |
|---|---|---|
| `so_strict_json_record` | single object, exactly 4 keys, strict, numeric types | valid_json (w3), required_fields strict (w4), field_type x2 (w2 each) |
| `so_json_array_filter` | filtered array, per-item shape | valid_json (w3), field_type `$` array (w2), required_fields (w4) |

## Known limitations (stated up front)

- The scorer verifies SHAPE, not value correctness: a wrong-but-well-typed
  value passes (content-correctness of values is out of v0.1 scorer scope,
  per G3; human review or future tooling covers it).
- First-position-only extraction is deliberately strict: prose-prefixed JSON
  fails even when valid JSON follows. That is the "exactly one JSON
  document" convention, stated openly.
- No nested-path checking in v0.1 (flat field contracts only).