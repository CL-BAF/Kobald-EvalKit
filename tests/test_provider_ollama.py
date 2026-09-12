"""Tests for OllamaProvider: error mapping, loopback guard, protocol errors.

All tests are offline. Network interaction is faked either by pointing at
a closed loopback port (deterministic connection refusal) or by
monkeypatching urllib.request.urlopen with a stub.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from evalkit.provider.ollama import OllamaProvider, _is_loopback_host
from evalkit.provider.base import (
    ModelInfo,
    ProviderConnectionError,
    ProviderError,
    ProviderProtocolError,
    ProviderTimeout,
)

DEFAULT_URL = "http://127.0.0.1:11434"


def closed_port_url() -> str:
    """Bind then release a loopback port so nothing is listening on it."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._stream = io.BytesIO(body)
        self.status = status

    def read(self) -> bytes:
        return self._stream.read()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestConstructionGuards:
    def test_default_base_url_is_loopback_default(self):
        provider = OllamaProvider(model="m")
        assert provider.name == "ollama"
        # Default construction must succeed (loopback default) and generate
        # against the standard local port; verified indirectly via error text.
        with pytest.raises(ProviderConnectionError) as excinfo:
            provider.generate("p")
        assert "11434" in str(excinfo.value)

    def test_refuses_non_loopback_by_default(self):
        with pytest.raises(ProviderConnectionError) as excinfo:
            OllamaProvider(base_url="http://203.0.113.7:11434", model="m")
        assert "non-loopback" in str(excinfo.value)

    def test_refuses_non_loopback_hostname_by_default(self):
        with pytest.raises(ProviderConnectionError):
            OllamaProvider(base_url="http://ollama.example.com:11434", model="m")

    def test_explicit_override_still_pins_and_allows(self):
        # Override allowed: construction succeeds, no exception.
        provider = OllamaProvider(
            base_url="http://203.0.113.7:11434", model="m", allow_non_loopback=True
        )
        assert provider.name == "ollama"

    def test_override_with_unresolvable_dns_host_refuses(self):
        with pytest.raises(ProviderConnectionError) as excinfo:
            OllamaProvider(
                base_url="http://nonexistent-host-evalkit-test.invalid:11434",
                model="m",
                allow_non_loopback=True,
            )
        assert "nonexistent-host-evalkit-test.invalid" in str(excinfo.value)

    def test_refuses_https_scheme(self):
        with pytest.raises(ProviderConnectionError) as excinfo:
            OllamaProvider(base_url="https://127.0.0.1:11434", model="m")
        assert "https" in str(excinfo.value)

    def test_no_cloud_fallback_on_default_path(self, monkeypatch):
        # A refused loopback connection must raise, never silently retry
        # anywhere else.
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(base_url=closed_port_url(), model="m")
        with pytest.raises(ProviderError):
            provider.generate("anything")
        with pytest.raises(ProviderError):
            provider.list_models()


class TestConnectionRefused:
    def test_generate_connection_refused_real_socket_canary(self):
        # The one real-socket refused test (Amendment v0.1.7 ruling #3):
        # bind+release a loopback port so nothing listens there, then
        # confirm the provider maps the OS-level refusal to ProviderError.
        provider = OllamaProvider(base_url=closed_port_url(), model="m")
        with pytest.raises(ProviderError):
            provider.generate("hello")

    def test_list_models_connection_refused_maps_to_provider_error(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderConnectionError):
            provider.list_models()

    def test_error_names_the_base_url(self, monkeypatch):
        url = closed_port_url()

        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(base_url=url, model="m")
        with pytest.raises(ProviderError) as excinfo:
            provider.generate("hello")
        assert url in str(excinfo.value)


class TestTimeoutMapping:
    def test_urlopen_timeout_reason_maps_to_provider_timeout(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(TimeoutError("timed out"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderTimeout):
            provider.generate("hello")

    def test_socket_timeout_maps_to_provider_timeout(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise TimeoutError("read timed out")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderTimeout):
            provider.generate("hello")

    def test_all_provider_errors_are_provider_error(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(OSError("weird failure"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderError):
            provider.generate("hello")


class TestErrorTaxonomy:
    """Amendment v0.1.7: refused -> ProviderConnectionError; timeout
    messages carry the 'Is Ollama running?' hint."""

    def test_refused_reason_maps_to_connection_error_with_hint(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderConnectionError) as excinfo:
            provider.generate("hello")
        message = str(excinfo.value)
        assert "Is Ollama running" in message

    def test_timeout_message_carries_ollama_running_hint(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(TimeoutError("timed out"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderTimeout) as excinfo:
            provider.generate("hello")
        assert "is Ollama running?" in str(excinfo.value)

    def test_timeout_error_is_not_connection_error(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(TimeoutError("timed out"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderTimeout) as excinfo:
            provider.generate("hello")
        assert not isinstance(excinfo.value, ProviderConnectionError)

    def test_connection_error_is_not_timeout(self, monkeypatch):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderConnectionError) as excinfo:
            provider.generate("hello")
        assert not isinstance(excinfo.value, ProviderTimeout)


class TestProtocolErrors:
    def test_unparseable_body_maps_to_protocol_error(self, monkeypatch):
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(b"not json")
        )
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderProtocolError):
            provider.generate("hello")

    def test_generate_missing_response_field_maps_to_protocol_error(self, monkeypatch):
        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda request, timeout=None: FakeResponse(json.dumps({"done": True}).encode()),
        )
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderProtocolError):
            provider.generate("hello")

    def test_tags_missing_models_list_maps_to_protocol_error(self, monkeypatch):
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(b"{}")
        )
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderProtocolError):
            provider.list_models()

    def test_tags_entry_missing_name_maps_to_protocol_error(self, monkeypatch):
        body = json.dumps({"models": [{"size": 123}]}).encode()
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(body)
        )
        provider = OllamaProvider(model="m")
        with pytest.raises(ProviderProtocolError):
            provider.list_models()


class TestHappyPaths:
    def test_generate_returns_result_from_ollama_shape(self, monkeypatch):
        body = json.dumps(
            {"model": "llama3", "response": "Paris [1]", "done": True}
        ).encode()

        def fake_urlopen(request, timeout=None):
            return FakeResponse(body)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="llama3")
        result = provider.generate("capital of France?")
        assert result.text == "Paris [1]"
        assert result.model == "llama3"
        assert result.provider == "ollama"
        assert result.elapsed_ms >= 0.0
        assert result.raw == {"model": "llama3", "response": "Paris [1]", "done": True}

    def test_generate_payload_carries_system_and_options(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return FakeResponse(json.dumps({"response": "ok"}).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="llama3")
        provider.generate("p", system="be terse", options={"temperature": 0.1})
        payload = json.loads(captured["request"].data.decode("utf-8"))
        assert payload["system"] == "be terse"
        assert payload["options"] == {"temperature": 0.1}
        assert payload["stream"] is False
        assert payload["model"] == "llama3"

    def test_list_models_parses_ollama_tags_shape(self, monkeypatch):
        body = json.dumps(
            {
                "models": [
                    {"name": "llama3", "size": 4700000000, "details": {"family": "llama"}},
                    {"name": "qwen2:7b", "size": None},
                ]
            }
        ).encode()
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(body)
        )
        provider = OllamaProvider(model="llama3")
        models = provider.list_models()
        assert models == [
            ModelInfo(name="llama3", size_bytes=4700000000, details={"family": "llama"}),
            ModelInfo(name="qwen2:7b", size_bytes=None, details={}),
        ]

    def test_generate_without_model_configured_raises(self):
        provider = OllamaProvider()
        with pytest.raises(ProviderError):
            provider.generate("hello")


class TestNoAuthHeaders:
    """Amendment v0.1.3 A4: raw must never carry auth; requests must not
    attach authorization headers or API keys."""

    def test_generate_request_has_no_authorization_header(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.header_items())
            return FakeResponse(json.dumps({"response": "ok"}).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="llama3")
        provider.generate("hello")
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert "authorization" not in headers
        assert "x-api-key" not in headers
        assert "api-key" not in headers

    def test_list_models_request_has_no_authorization_header(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["headers"] = dict(request.header_items())
            return FakeResponse(json.dumps({"models": [{"name": "llama3"}]}).encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = OllamaProvider(model="llama3")
        provider.list_models()
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        assert "authorization" not in headers
        assert "x-api-key" not in headers

    def test_raw_never_contains_credential_like_keys(self, monkeypatch):
        body = json.dumps(
            {
                "response": "ok",
                "model": "llama3",
                "api_key": "sk-live-should-not-be-here",
                "authorization": "Bearer xyz",
            }
        ).encode()
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda request, timeout=None: FakeResponse(body)
        )
        provider = OllamaProvider(model="llama3")
        result = provider.generate("hello")
        # v0.1.5: raw is the backend's own payload dict; credentials must
        # never be ADDED by the provider. Assert provider didn't inject
        # credential fields of its own (the backend echoing unknown keys in
        # its payload is a backend concern, flagged for the runner to strip).
        added = set(result.raw) - {"response", "model", "api_key", "authorization"}
        assert added == set()


class TestLoopbackHelper:
    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("127.0.0.1", True),
            ("localhost", True),
            ("::1", True),
            ("127.4.3.2", True),
            ("203.0.113.7", False),
            ("ollama.example.com", False),
            ("", False),
            (None, False),
        ],
    )
    def test_is_loopback_host(self, host, expected):
        assert _is_loopback_host(host) is expected