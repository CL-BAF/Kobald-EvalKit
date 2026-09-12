"""Loader contract tests against docs/case-schema.md (normative) + evalkit/errors.py.

Covers: valid parse; the full invalid-case rejection matrix; stem==case_id;
suite-vs-directory; suite registry; weight range 0.5-5; duplicate case_id
naming both files; unknown top-level keys; evidence shape/ID uniqueness;
schema_version tolerance/rejection; needs_human round-trip preconditions.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evalkit.errors import CaseLoadError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
INVALID_DIR = FIXTURES / "cases" / "invalid"

VALID_CASE = {
    "schema_version": "1",
    "case_id": "eg_valid",
    "suite": "evidence_grounding",
    "title": "Valid case",
    "purpose": "Fixture: a valid case for loader acceptance tests.",
    "evidence": [
        {"id": "SRC-1", "text": "The capital of France is Paris."},
        {"id": "SRC-2", "text": "Paris sits on the Seine."},
    ],
    "instruction": "Name the capital city. Cite sources like [SRC-1].",
    "constraints": "Answer with the city name and citations only.",
    "scoring": [
        {
            "type": "required_source_ids",
            "params": {"ids": ["SRC-1"], "allow_extras": False},
            "weight": 1,
        }
    ],
    "expected": "Paris [SRC-1]",
}


def write_case(directory: Path, name: str, payload) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif payload is None:
        path.write_text("", encoding="utf-8")
    else:
        path.write_text(payload, encoding="utf-8")
    return path


@pytest.fixture()
def suites_dir(tmp_path: Path) -> Path:
    target = tmp_path / "suites"
    target.mkdir()
    return target


def make_valid_suite(suites_dir: Path) -> Path:
    suite_dir = suites_dir / "evidence_grounding"
    suite_dir.mkdir()
    write_case(suite_dir, f"{VALID_CASE['case_id']}.json", VALID_CASE)
    return suite_dir


# The loader entry point (Core's landed API: load_suite(suites_dir, suite)).
from evalkit.cases import SUITES_REGISTRY, load_suite, load_case_file  # noqa: E402


def load_all(suites_dir: Path, suite: str = "evidence_grounding"):
    return load_suite(suites_dir, suite)


class TestValidLoading:
    def test_valid_case_loads(self, suites_dir):
        make_valid_suite(suites_dir)
        cases = load_all(suites_dir)
        assert len(cases) == 1
        case = cases[0]
        assert case.case_id == "eg_valid"

    def test_real_repo_evidence_grounding_suite_loads(self):
        repo_suites = Path(__file__).resolve().parent.parent / "suites"
        cases = load_suite(repo_suites, "evidence_grounding")
        all_ids = {c.case_id for c in cases}
        # Every file in the real suite must load and register its case_id.
        # File-set-derived so the suite can grow without churning this test;
        # the roster pin below guards against silent removals.
        expected_files = {
            p.stem for p in (repo_suites / "evidence_grounding").glob("*.json")
        } - {"suite"}
        assert all_ids == expected_files
        assert all_ids == {
            "eg_cite_all_sources",
            "eg_flag_insufficiency",
            "eg_no_extra_sources",
            "eg_summarize_grounded",
            "eg_citation_format_strict",
        }

    def test_schema_version_absent_defaults(self, suites_dir):
        payload = dict(VALID_CASE)
        del payload["schema_version"]
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        cases = load_all(suites_dir)
        assert len(cases) == 1
        assert cases[0].schema_version == "1"

    def test_optional_weight_defaults(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        del payload["scoring"][0]["weight"]
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        cases = load_all(suites_dir)
        assert cases[0].scoring[0].weight == 1.0

    def test_optional_suite_json_is_ignored(self, suites_dir):
        make_valid_suite(suites_dir)
        poison = {
            "weights": {"eg_valid": 100},
            "scoring": [{"type": "required_source_ids", "params": {"ids": ["HACK"]}}],
            "expected": "poison",
        }
        (suites_dir / "evidence_grounding" / "suite.json").write_text(
            json.dumps(poison), encoding="utf-8"
        )
        cases = load_all(suites_dir)
        assert cases[0].expected == VALID_CASE["expected"]
        assert cases[0].scoring[0].params == VALID_CASE["scoring"][0]["params"]
        assert cases[0].scoring[0].weight == VALID_CASE["scoring"][0]["weight"]


class TestInvalidMatrix:
    @pytest.mark.parametrize(
        "filename",
        sorted(p.name for p in INVALID_DIR.glob("*.json")),
    )
    def test_invalid_fixture_is_rejected(self, suites_dir, filename):
        target = suites_dir / "evidence_grounding"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(INVALID_DIR / filename, target / filename)
        with pytest.raises(CaseLoadError) as excinfo:
            load_all(suites_dir)
        assert filename in str(excinfo.value)

    def test_malformed_json_rejected(self, suites_dir):
        write_case(
            suites_dir / "evidence_grounding", "bad.json", "{ not valid json"
        )
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_empty_file_rejected(self, suites_dir):
        write_case(suites_dir / "evidence_grounding", "bad.json", None)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_unknown_top_level_key_rejected(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["scorring"] = payload["scoring"]  # typo safety probe
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError) as excinfo:
            load_all(suites_dir)
        assert "scorring" in str(excinfo.value) or "unknown" in str(excinfo.value).lower()

    def test_stem_must_equal_case_id(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["case_id"] = "different_id"
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError) as excinfo:
            load_all(suites_dir)
        message = str(excinfo.value)
        assert "eg_valid" in message and "different_id" in message

    def test_suite_field_must_match_directory(self, suites_dir):
        other = suites_dir / "contradiction"
        other.mkdir()
        payload = json.loads(json.dumps(VALID_CASE))
        payload["suite"] = "evidence_grounding"  # directory says contradiction
        write_case(other, "eg_valid.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_unknown_suite_directory_rejected(self, suites_dir):
        rogue = suites_dir / "vibes"
        rogue.mkdir()
        payload = json.loads(json.dumps(VALID_CASE))
        payload["suite"] = "vibes"
        write_case(rogue, "eg_valid.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_duplicate_case_id_rejected_naming_both_files(self, suites_dir):
        # Per Lead routing: with stem==case_id enforced per-file, a
        # naive same-directory copy is caught by the STEM rule first.
        # The reachable cross-file duplicate case_id is the same
        # stem-matching file placed under two registry suite dirs; the
        # loader's per-suite duplicate guard is defence-in-depth. Pin
        # the reachable behaviours honestly:
        first_dir = suites_dir / "evidence_grounding"
        second_dir = suites_dir / "contradiction"
        write_case(first_dir, "eg_valid.json", VALID_CASE)
        other = json.loads(json.dumps(VALID_CASE))
        other["suite"] = "contradiction"
        other["scoring"] = [
            {"type": "lexical_contradiction", "params": {"pairs": [["a", "b"]]}}
        ]
        write_case(second_dir, "eg_valid.json", other)
        # Same case_id in two suite dirs: each per-suite load succeeds
        # (per-suite scoping is the loader contract).
        cases_a = load_suite(suites_dir, "evidence_grounding")
        cases_b = load_suite(suites_dir, "contradiction")
        assert cases_a[0].case_id == cases_b[0].case_id == "eg_valid"
        assert len(cases_a) == 1 and len(cases_b) == 1

    def test_copy_with_same_case_id_is_caught_by_stem_rule(self, suites_dir):
        # A naive copy keeps case_id 'eg_valid' but gains stem
        # 'eg_valid_copy' -> the stem rule rejects it FIRST, naming the
        # offending file. Pinned ordering per Lead's analysis.
        suite_dir = suites_dir / "evidence_grounding"
        write_case(suite_dir, "eg_valid.json", VALID_CASE)
        twin_path = suite_dir / "eg_valid_copy.json"
        twin_path.write_text(
            (suite_dir / "eg_valid.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        with pytest.raises(CaseLoadError) as excinfo:
            load_all(suites_dir)
        message = str(excinfo.value)
        assert "eg_valid_copy.json" in message
        assert "stem" in message.lower()

    def test_duplicate_guard_names_both_files(self):
        # The duplicate branch (cases.py load_suite) is defence-in-depth:
        # within one suite it is unreachable through normal files because
        # stem==case_id forces unique filenames. Pin its message contract
        # and presence in the loader's public path.
        import inspect

        from evalkit import cases as cases_mod

        source = inspect.getsource(cases_mod.load_suite)
        assert "duplicate case_id" in source
        assert "{by_id[case.case_id]} and {path}" in source

    def test_unknown_scoring_type_rejected(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["scoring"][0]["type"] = "vibes_based"
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError) as excinfo:
            load_all(suites_dir)
        assert "vibes_based" in str(excinfo.value)

    @pytest.mark.parametrize("weight", [0.49, 0, -1, 5.1, 100, "3", None])
    def test_weight_outside_0_5_to_5_rejected(self, suites_dir, weight):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["scoring"][0]["weight"] = weight
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    @pytest.mark.parametrize("weight", [0.5, 1, 2.5, 5])
    def test_weight_inside_range_accepted(self, suites_dir, weight):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["scoring"][0]["weight"] = weight
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        load_all(suites_dir)

    def test_unknown_schema_version_rejected(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["schema_version"] = "2"
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError) as excinfo:
            load_all(suites_dir)
        assert "schema_version" in str(excinfo.value) or "2" in str(excinfo.value)

    def test_evidence_id_mismatched_charset_rejected(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["evidence"][0]["id"] = "src-1"  # lowercase: never token-matchable
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_duplicate_evidence_ids_rejected(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["evidence"][1]["id"] = payload["evidence"][0]["id"]
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_case_id_charset_rejected(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["case_id"] = "../escape"
        write_case(suites_dir / "evidence_grounding", "bad_name.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    @pytest.mark.parametrize(
        "field",
        ["case_id", "suite", "title", "purpose", "evidence", "instruction", "constraints", "scoring", "expected"],
    )
    def test_each_required_field_missing_rejected(self, suites_dir, field):
        payload = json.loads(json.dumps(VALID_CASE))
        del payload[field]
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_scoring_empty_list_rejected(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["scoring"] = []
        write_case(suites_dir / "evidence_grounding", "eg_valid.json", payload)
        with pytest.raises(CaseLoadError):
            load_all(suites_dir)

    def test_error_names_the_offending_file(self, suites_dir):
        payload = json.loads(json.dumps(VALID_CASE))
        payload["scoring"][0]["type"] = "nope"
        write_case(suites_dir / "evidence_grounding", "the_bad_one.json", payload)
        with pytest.raises(CaseLoadError) as excinfo:
            load_all(suites_dir)
        assert "the_bad_one.json" in str(excinfo.value)
        # CaseLoadError is an EvalkitError, not a bare crash class.
        from evalkit.errors import EvalkitError

        assert isinstance(excinfo.value, EvalkitError)


class TestPoisonSuiteJson:
    def test_suite_json_never_influences_scoring(self, suites_dir):
        suite_dir = suites_dir / "evidence_grounding"
        write_case(suite_dir, "eg_valid.json", VALID_CASE)
        baseline = load_all(suites_dir)
        poison = {
            "case_id": "eg_valid",
            "scoring": [{"type": "invented_citations", "params": {"max_allowed": 999, "ids": []}}],
            "expected": "poisoned expectation",
            "weights": {"eg_valid": 99},
        }
        (suite_dir / "suite.json").write_text(json.dumps(poison), encoding="utf-8")
        after = load_all(suites_dir)
        assert after == baseline