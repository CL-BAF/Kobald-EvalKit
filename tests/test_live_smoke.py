"""Live Ollama smoke test — REQUIRES a running local Ollama.

Excluded by default via pyproject addopts ("-m \"not live\"); run
explicitly with: pytest -m live

Kept tiny on purpose: one discovery + one generation. Not deterministic
(the model answers), so asserts are structural, not content.
"""

from __future__ import annotations

import os

import pytest

from evalkit.config import EvalKitConfig, build_provider

live = pytest.mark.live

_OLLAMA_URL = os.environ.get("EVALKIT_OLLAMA_URL", "http://127.0.0.1:11434")
_MODEL = os.environ.get("EVALKIT_OLLAMA_MODEL", "")


@live
def test_ollama_discover_and_generate():
    config = EvalKitConfig(provider="ollama", model=_MODEL, base_url=_OLLAMA_URL, timeout_s=30.0)
    provider = build_provider(config)
    models = provider.list_models()
    assert isinstance(models, list)
    if not models:
        pytest.skip("no models pulled in local Ollama")
    model_name = _MODEL or models[0].name
    result = provider.generate("Reply with exactly: ok")
    assert isinstance(result.text, str)
    assert result.provider == "ollama"
    assert result.elapsed_ms >= 0.0
    # Model echo may differ from config; the contract only fixes fields.
    assert isinstance(result.raw, dict)


@live
def test_live_end_to_end_run_via_cli(tmp_path):
    """Full CLI run against live Ollama, if a model is available."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "evalkit.cli",
            "run",
            "evidence_grounding",
            "--provider",
            "ollama",
            "--model",
            _MODEL or "llama3.1:8b",
            "--timeout",
            "60",
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        timeout=600,
    )
    if proc.returncode != 0 and "nothing is listening" in proc.stdout + proc.stderr:
        pytest.skip("no live Ollama at default URL")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "cases:" in proc.stdout