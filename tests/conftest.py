"""Shared pytest bootstrap for EvalKit tests.

Runs from the repo root without requiring an installed package: the
repository root is added to sys.path so ``import evalkit`` resolves to
the source tree. All tests are offline by default; the live Ollama
smoke test is separately marked.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

__all__ = ["REPO_ROOT", "FIXTURES_DIR"]