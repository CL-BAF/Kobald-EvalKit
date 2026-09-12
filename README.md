# Kobald EvalKit

Standalone, open-source local AI evaluation toolkit. Repeatable behavioural
tests for local models, starting with [Ollama](https://ollama.com). Not a
universal intelligence score — a way to re-run the same behavioural probes
against the same model with the same options and see exactly what passed,
what failed, and what needs a human.

- Python >= 3.10, **stdlib-only runtime** (pytest only for development).
- Deterministic scoring: same response + same case = same result, forever.
- Unreliable judgement is explicitly flagged `needs_human`, never guessed.
- Local-only posture: talks to a loopback Ollama endpoint by default; no
  telemetry, no cloud, no credential handling.

## Install

```bash
git clone https://github.com/CL-BAF/Kobald-EvalKit
cd Kobald-EvalKit
python -m pip install -e .
```

Requires an Ollama server (`ollama serve`) for real runs. No network access
beyond your configured endpoint.

## Quick start

```bash
# health check: config, suites dir, provider reachability
evalkit doctor --provider ollama --model llama3.1:8b

# what can this local server see?
evalkit models --provider ollama

# what suites/cases exist?
evalkit list

# offline dry-run with the built-in mock provider (no server needed)
evalkit run evidence_grounding --provider mock

# for real: run a suite against a local model
evalkit run evidence_grounding --provider ollama --model llama3.1:8b

# read a stored run
evalkit report 20260912T121951Z-109de87e

# compare two runs of the same suite/model/options
evalkit compare <run_a> <run_b>
```

Every `run` persists `runs/<run_id>/result.json` + `report.md`
(`run_id = UTC timestamp + 8 hex chars`). The terminal summary shows
per-case PASS/FAIL/HUMAN/ERROR plus the weighted pass rate; the Markdown
report includes every check's detail, the aggregate formula, and its
limitations.

## How scoring works (the honest version)

Each case declares `scoring[]` rules — the **only** enforcement source
(the `expected` field is documentation for humans). Rules are deterministic
string/regex/JSON checks, e.g. `required_source_ids`, `invented_citations`,
`valid_json`, `lexical_contradiction`, `insufficiency_marker`. The full
registry and the exact semantics live in [`docs/scoring.md`](docs/scoring.md);
the case schema is [`docs/case-schema.json`](docs/case-schema.json) with a
human-readable version in [`docs/case-schema.md`](docs/case-schema.md).

Semantics, pinned:

- A check either computes a definite pass/fail or is marked `needs_human`.
  A `needs_human` check never silently passes or fails a case — it reports
  "not verified by automation" and the case is listed separately.
- `passed` = every non-`needs_human` check passed. Weights never affect
  pass/fail, only the reported aggregate.
- Aggregate: `weighted_pass_rate = sum(weights of passed cases) /
  sum(weights of all scored cases)` over non-`needs_human` cases only.
  Limitations: weights are design choices, not measured importance; cases
  are small probes, not a representative sample; rates across different
  models/quantisations/option sets are not comparable unless you control
  those variables. **No overall "score" is published.**

What is deliberately **not** automated: judging truth, paraphrase
faithfulness, subtle (non-lexical) contradictions, anything about model
"intelligence". Those would need fuzzy judgement; EvalKit flags them
`needs_human` with instructions instead of emitting numbers.

## Suites (v0.1)

| suite | cases | tests |
|---|---|---|
| `evidence_grounding` | 5 | citation discipline: required IDs, no invented citations, marker honesty |
| `fabricated_citations` | 2 | citation-shaped artefacts (brackets, DOIs, arXiv, ISBN) under no-evidence and real-sounding conditions |
| `structured_output` | 2 | valid JSON, required fields, field types |
| `uncertainty` | 2 | marker discrimination: flag insufficiency when evidence lacks the figure, restrain when it has it |
| `contradiction` | 2 | rule-based assertion consistency (no blending of planted misstatements) |
| `mixed_evidence` | — | planned: weigh conflicting evidence (needs_human by design) |

All suite content is invented (fictional towns, studies, records) and
redistributable. See [`docs/suites/`](docs/suites/) and
[`docs/sketches/`](docs/sketches/) for design notes.

## CLI reference

```
evalkit doctor    [--provider mock|ollama] [--model TAG] [--base-url URL]
                  [--timeout SEC] [--allow-non-loopback] [--config FILE]
evalkit models    [same options]         # JSON, data-first, ':cloud' flags attached
evalkit list      [--suite NAME]         # registry suites with case files
evalkit run       SUITE|--all-implicit   # see: evalkit run --help
evalkit report    RUN_ID
evalkit compare   RUN_A RUN_B
```

Exit codes: `0` success, `1` runtime error (clean stderr message, no
traceback), `2` usage error. `doctor` exits `0` when the provider is
reachable, `1` when not.

Notes on behaviour you should know about:

- **`:cloud` model tags are flagged, not filtered.** EvalKit constrains the
  *endpoint* (loopback), not the model tag: selecting a `:cloud` model
  routes inference off-machine. `doctor`/`models` attach a warning; the
  README states it here — that is the whole safeguard in v0.1.
- **`--allow-non-loopback` is an explicit override** (config file or CLI
  flag only — never an environment variable). Traffic to a non-loopback
  Ollama is cleartext HTTP; the override is echoed plainly by `doctor` and
  flagged in the generated report.
- **Model output is untrusted input**: it is only regex-counted or
  JSON-parsed, never executed.
- **`result.json` redacts credential-shaped keys** from provider metadata
  (case-insensitive, visible `[redacted]` marker — never silently dropped)
  before the atomic write.
- **Comparing runs is guarded**: `compare` refuses mismatched
  model/provider/base-url/options/suite-sets or incompatible EvalKit
  versions instead of producing a meaningless delta.

## Configuration

Optional `evalkit.json` in the project root (or `--config PATH`):

```json
{
  "provider": "ollama",
  "model": "llama3.1:8b",
  "base_url": "http://127.0.0.1:11434",
  "timeout_s": 120,
  "allow_non_loopback": false,
  "options": {"temperature": 0},
  "suites_dir": "suites",
  "runs_dir": "runs"
}
```

Unknown keys are rejected (typo safety). CLI flags override file values;
`allow_non_loopback` cannot be enabled via environment variable by design.

## Development

```bash
python -m pytest          # offline suite (live Ollama smoke is marked, excluded by default)
python -m pytest -m live  # requires a running Ollama server
```

Layout: `evalkit/` (CLI, config, loader, runner, scoring, store, reports),
`suites/` (JSON case files), `tests/`, `docs/`. Runtime dependencies:
none. See [`docs/case-schema.md`](docs/case-schema.md) to write cases and
[`docs/scoring.md`](docs/scoring.md) for the scorer registry and its
honesty contract.

## License

[MIT](LICENSE)