"""Provider contracts for EvalKit.

Providers turn a prompt into a GenerationResult and expose local model
discovery. They know nothing about cases or scoring; scoring logic stays
out of this package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

__all__ = [
    "ModelInfo",
    "GenerationResult",
    "ProviderError",
    "ProviderConnectionError",
    "ProviderTimeout",
    "ProviderProtocolError",
    "Provider",
]


@dataclass(frozen=True)
class ModelInfo:
    """One locally available model as reported by the provider."""

    name: str
    size_bytes: int | None = None
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationResult:
    """The outcome of a single generation attempt.

    elapsed_ms is a float in milliseconds (>= 0.0), measured inside the
    provider, so the runner never has to scrape raw payloads for timing.
    Docs rule: sub-millisecond latency is never published as a claim
    (mock timings collapse to 0). raw holds the backend's own response
    metadata and is always a dict, never None. Providers never INJECT
    credential-like keys into raw or request headers (v0.1.8); raw
    passes backend content through as-is, and persistence-level
    redaction of credential-like keys is the store's responsibility.
    """

    text: str
    model: str
    provider: str
    elapsed_ms: float
    raw: dict = field(default_factory=dict)


class ProviderError(Exception):
    """Base class for all provider failures."""


class ProviderConnectionError(ProviderError):
    """The provider backend could not be reached."""


class ProviderTimeout(ProviderError):
    """The provider backend did not answer in time."""


class ProviderProtocolError(ProviderError):
    """The backend answered but the body was unusable (unparseable JSON
    or missing required fields). Runs degrade per-case on this instead
    of aborting."""


class Provider(ABC):
    """Bounded interface EvalKit uses to talk to a model backend."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable provider identifier, e.g. 'ollama'."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        options: dict | None = None,
    ) -> GenerationResult:
        """Generate a completion for prompt. Expected failure modes raise
        ProviderError subclasses only: connection problems raise
        ProviderConnectionError, slow backends raise ProviderTimeout,
        unusable response bodies raise ProviderProtocolError."""

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """List models available through this provider."""