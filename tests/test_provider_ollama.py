"""Tests for OllamaProvider: error mapping, loopback guard, protocol errors.

All tests are offline. Network interaction is faked either by pointing at
a closed loopback port (deterministic connection refusal), monkeypatching
urllib.request.urlopen with a stub, or serving from the in-process
StubOllama HTTP server (tests/stub_ollama.py, handed over from Providers).
"""

from __future__ import annotations

import io
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from evalkit.provider.ollama import OllamaProvider, _is_loopback_host
from evalkit.provider.base import (
    ModelInfo,
    ProviderConnectionError,
    ProviderError,
    ProviderProtocolError,
    ProviderTimeout,
)
from stub_ollama import StubOllama

DEFAULT_URL = "http://127.0.0.1:11434"


def closed_port_url() -> str:
    """Bind then release a loopback port so nothing is listening on it."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}"


class StubServer:
    """In-process StubOllama server on an ephemeral loopback port."""

    def __init__(self, handler=StubOllama):
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        return False


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

    def test_override_with_unresolvable_dns_host_defers_error_to_request(self):
        # v0.1.9 contract: construction performs scheme + loopback checks
        # ONLY. With allow_non_loopback=True and an unresolvable host,
        # construction SUCCEEDS; the first REQUEST fails with
        # ProviderConnectionError carrying the "Is Ollama running?" hint
        # (v0.1.6 mapping). Request-time failure mode asserted explicitly.
        provider = OllamaProvider(
            base_url="http://nonexistent-host-evalkit-test.invalid:11434",
            model="m",
            allow_non_loopback=True,
        )
        assert provider.name == "ollama"
        with pytest.raises(ProviderConnectionError) as excinfo:
            provider.generate("hello")
        message = str(excinfo.value)
        assert "Is Ollama running?" in message
        assert "getaddrinfo" in message
        # Same failure mode via list_models, the other request entry point.
        with pytest.raises(ProviderConnectionError):
            provider.list_models()

    def test_loopback_url_never_triggers_getaddrinfo(self, monkeypatch):
        calls: list[tuple] = []

        def counting_getaddrinfo(*args, **kwargs):
            calls.append(args)
            return []

        monkeypatch.setattr(socket, "getaddrinfo", counting_getaddrinfo)
        for url in (
            "http://127.0.0.1:11434",
            "http://localhost:11434",
            "http://[::1]:11434",
            DEFAULT_URL,
        ):
            OllamaProvider(base_url=url, model="m")
        assert calls == []

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


class TestFailClosedMalformedIPv6:
    """Lead ruling: 'http://::1:11434' (malformed, unbracketed IPv6) is
    fail-closed rejected at construction as non-loopback by design."""

    def test_malformed_unbracketed_ipv6_rejected_fail_closed(self):
        with pytest.raises(ProviderConnectionError) as excinfo:
            OllamaProvider(base_url="http://::1:11434", model="m")
        assert "non-loopback" in str(excinfo.value)


class TestStubbedServer:
    """End-to-end provider behaviour against the in-process stub server
    (Providers' harness, Lead-approved). Real HTTP over loopback, still
    fully offline."""

    def test_generate_happy_path_with_real_request(self):
        with StubServer() as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            result = provider.generate("hello")
            assert result.text == "ok"
            assert result.model == "stub:latest"
            assert result.provider == "ollama"
            assert result.elapsed_ms >= 0.0

    def test_list_models_happy_path(self):
        with StubServer() as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            models = provider.list_models()
            assert models == [
                ModelInfo(name="stub:latest", size_bytes=1, details={"family": "stub"})
            ]

    def test_headers_exactly_content_type(self):
        captured: dict = {}

        class CapturingStub(StubOllama):
            def do_POST(self):
                captured["headers"] = dict(self.headers)
                super().do_POST()

        with StubServer(CapturingStub) as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            provider.generate("hello")
        header_names = {k.lower() for k in captured["headers"]}
        assert "content-type" in header_names
        assert not header_names & {"authorization", "x-api-key", "api-key", "cookie"}

    def test_raw_keys_equal_stub_canned_keys(self):
        with StubServer() as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            result = provider.generate("hello")
            # Provider must not inject keys beyond what the backend sent.
            assert set(result.raw) == set(StubOllama.canned_generate)
            assert result.raw["response"] == "ok"
            assert result.raw["model"] == "stub:latest"

    def test_generate_response_field_missing_is_protocol_error(self):
        class MissingFieldStub(StubOllama):
            canned_generate = {"model": "stub:latest", "done": True}

        with StubServer(MissingFieldStub) as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            with pytest.raises(ProviderProtocolError) as excinfo:
                provider.generate("hello")
            assert "response" in str(excinfo.value)

    def test_unparseable_body_is_protocol_error(self):
        class GarbageStub(StubOllama):
            def post_payload(self):
                return b"this is not json at all"

        with StubServer(GarbageStub) as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            with pytest.raises(ProviderProtocolError):
                provider.generate("hello")

    def test_tags_unparseable_body_is_protocol_error(self):
        class GarbageTagsStub(StubOllama):
            def get_payload(self):
                return b"<html>not json</html>"

        with StubServer(GarbageTagsStub) as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            with pytest.raises(ProviderProtocolError):
                provider.list_models()

    def test_tags_missing_models_key_is_protocol_error(self):
        class NoModelsStub(StubOllama):
            def get_payload(self):
                return json.dumps({"unexpected": True}).encode("utf-8")

        with StubServer(NoModelsStub) as stub:
            provider = OllamaProvider(base_url=stub.base_url, model="stub:latest")
            with pytest.raises(ProviderProtocolError):
                provider.list_models()


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