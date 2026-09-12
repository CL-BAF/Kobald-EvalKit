"""Shared exception hierarchy for EvalKit core.

EvalkitError and its subclasses are runtime/configuration failures the CLI
maps to exit code 1 with a clear stderr message (no traceback). Provider
failures use the ProviderError family from evalkit.provider.base.
"""

from __future__ import annotations

__all__ = [
    "EvalkitError",
    "ConfigError",
    "CaseLoadError",
    "ScoringError",
    "StoreError",
    "CompareError",
]


class EvalkitError(Exception):
    """Base class for EvalKit core failures reported to the user."""


class ConfigError(EvalkitError):
    """Invalid or contradictory configuration."""


class CaseLoadError(EvalkitError):
    """A case file failed validation. Messages always name the file."""


class ScoringError(EvalkitError):
    """A scoring rule could not be applied."""


class StoreError(EvalkitError):
    """Run storage failed (allocation, write, or corrupt result.json)."""


class CompareError(EvalkitError):
    """Two runs cannot be compared (incompatible configs or shapes)."""