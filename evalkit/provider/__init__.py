"""Model backend adapters. Scoring logic does not live here."""

from .base import (
    GenerationResult,
    ModelInfo,
    Provider,
    ProviderConnectionError,
    ProviderError,
    ProviderProtocolError,
    ProviderTimeout,
)
from .mock import MockProvider, ScriptedResponse
from .ollama import OllamaProvider

__all__ = [
    "GenerationResult",
    "ModelInfo",
    "Provider",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderProtocolError",
    "ProviderTimeout",
    "MockProvider",
    "ScriptedResponse",
    "OllamaProvider",
]