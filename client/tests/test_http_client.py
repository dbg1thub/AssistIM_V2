from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")

    class _DummyClientError(Exception):
        pass

    class _DummyClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _DummyFormData:
        def __init__(self):
            self.fields = []

        def add_field(self, name, value, **kwargs):
            self.fields.append({"name": name, "value": value, **kwargs})

    class _DummyClientSession:
        def __init__(self, *args, **kwargs):
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _DummyClientResponse:
        status = 200

    aiohttp.ClientError = _DummyClientError
    aiohttp.FormData = _DummyFormData
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientResponse = _DummyClientResponse
    sys.modules["aiohttp"] = aiohttp

from client.core.exceptions import APIError, AuthExpiredError
from client.network.http_client import HTTPClient


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = "", body: bytes = b"") -> None:
        self.status = status
        self._payload = payload if payload is not None else {}
        self._text = text
        self._body = bytes(body or b"")

    async def json(self) -> dict:
        return dict(self._payload)

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._body or self._text.encode("utf-8")

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakeStreamContent:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]
        self._index = 0

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self) -> bytes:
        if self._index >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._index]
        self._index += 1
        return line


class FakeStreamResponse(FakeResponse):
    def __init__(self, status: int, lines: list[str], payload: dict | None = None, text: str = "") -> None:
        super().__init__(status=status, payload=payload, text=text)
        self.content = FakeStreamContent(lines)


class FakeSession:
    def __init__(self, request_handler=None, post_handler=None) -> None:
        self.closed = False
        self.request_calls: list[dict] = []
        self.post_calls: list[dict] = []
        self._request_handler = request_handler or self._default_request_handler
        self._post_handler = post_handler or self._default_post_handler

    def request(self, method: str, url: str, params=None, json=None, headers=None):
        call = {
            "method": method,
            "url": url,
            "params": params,
            "json": json,
            "headers": dict(headers or {}),
        }
        self.request_calls.append(call)
        return self._request_handler(**call)

    def post(self, url: str, json=None, headers=None, data=None):
        call = {
            "url": url,
            "json": json,
            "headers": dict(headers or {}),
            "data": data,
        }
        self.post_calls.append(call)
        return self._post_handler(**call)

    async def close(self) -> None:
        self.closed = True

    @staticmethod
    def _default_request_handler(**_kwargs) -> FakeResponse:
        return FakeResponse(500, {"message": "request handler not configured"})

    @staticmethod
    def _default_post_handler(**_kwargs) -> FakeResponse:
        return FakeResponse(500, {"message": "post handler not configured"})


def _write_upload_fixture(name: str) -> Path:
    workspace_tmp = Path("client/tests/.pytest_tmp")
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    file_path = workspace_tmp / name
    file_path.write_bytes(b"upload-data")
    return file_path


def test_http_client_absolute_url_skips_base_url_and_app_auth() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("app-access", "refresh-token")

        fake_session = FakeSession(
            request_handler=lambda **_kwargs: FakeResponse(200, {"data": {"ok": True}}),
        )
        client._session = fake_session

        payload = await client.post("http://localhost:11434/api/chat", json={"message": "hello"})

        assert payload == {"ok": True}
        assert len(fake_session.request_calls) == 1
        call = fake_session.request_calls[0]
        assert call["url"] == "http://localhost:11434/api/chat"
        assert "Authorization" not in call["headers"]

        await client.close()

    asyncio.run(scenario())


def test_http_client_external_401_does_not_trigger_app_refresh() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("app-access", "refresh-token")

        refresh_calls = 0

        async def fake_refresh() -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            return True

        client._refresh_access_token = fake_refresh  # type: ignore[method-assign]
        client._session = FakeSession(
            request_handler=lambda **_kwargs: FakeResponse(401, {"message": "bad provider key", "code": 40101}),
        )

        with pytest.raises(APIError) as exc_info:
            await client.post("https://api.openai.com/v1/chat/completions", json={"model": "gpt-4o-mini"})

        assert exc_info.value.message == "bad provider key"
        assert exc_info.value.status_code == 401
        assert refresh_calls == 0

        await client.close()

    asyncio.run(scenario())


def test_http_client_patch_uses_patch_method() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        fake_session = FakeSession(
            request_handler=lambda **call: FakeResponse(200, {"data": {"method": call["method"], "json": call["json"]}}),
        )
        client._session = fake_session

        payload = await client.patch("/groups/group-1", json={"name": "Renamed"})

        assert payload == {"method": "PATCH", "json": {"name": "Renamed"}}
        assert fake_session.request_calls == [
            {
                "method": "PATCH",
                "url": "http://app.local/api/v1/groups/group-1",
                "params": None,
                "json": {"name": "Renamed"},
                "headers": {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            }
        ]

        await client.close()

    asyncio.run(scenario())


def test_http_client_download_bytes_uses_absolute_url_without_app_auth() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("app-access", "refresh-token")
        fake_session = FakeSession(
            request_handler=lambda **_kwargs: FakeResponse(200, body=b"secret-bytes"),
        )
        client._session = fake_session

        payload = await client.download_bytes("https://cdn.example/files/secret.bin")

        assert payload == b"secret-bytes"
        assert fake_session.request_calls == [
            {
                "method": "GET",
                "url": "https://cdn.example/files/secret.bin",
                "params": None,
                "json": None,
                "headers": {
                    "Accept": "*/*",
                },
            }
        ]

        await client.close()

    asyncio.run(scenario())


def test_http_client_download_bytes_uses_origin_url_for_root_relative_media() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("app-access", "refresh-token")
        fake_session = FakeSession(
            request_handler=lambda **_kwargs: FakeResponse(200, body=b"cipher-bytes"),
        )
        client._session = fake_session

        payload = await client.download_bytes("/uploads/2026/04/17/secret.bin")

        assert payload == b"cipher-bytes"
        assert fake_session.request_calls == [
            {
                "method": "GET",
                "url": "http://app.local/uploads/2026/04/17/secret.bin",
                "params": None,
                "json": None,
                "headers": {
                    "Accept": "*/*",
                    "Authorization": "Bearer app-access",
                },
            }
        ]

        await client.close()

    asyncio.run(scenario())


def test_http_client_internal_401_refresh_is_singleflight() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("old-access", "refresh-token")

        refresh_calls = 0

        async def fake_perform_refresh(*_args) -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            await asyncio.sleep(0.01)
            client.set_tokens("new-access", "refresh-token-2")
            return True

        client._perform_token_refresh = fake_perform_refresh  # type: ignore[method-assign]

        def request_handler(**call) -> FakeResponse:
            authorization = call["headers"].get("Authorization")
            if authorization == "Bearer old-access":
                return FakeResponse(401, {"message": "token expired"})
            if authorization == "Bearer new-access":
                return FakeResponse(200, {"data": {"url": call["url"]}})
            return FakeResponse(500, {"message": f"unexpected auth header: {authorization}"})

        fake_session = FakeSession(request_handler=request_handler)
        client._session = fake_session

        results = await asyncio.gather(
            client.get("/profile"),
            client.get("/sessions"),
        )

        assert results == [
            {"url": "http://app.local/api/v1/profile"},
            {"url": "http://app.local/api/v1/sessions"},
        ]
        assert refresh_calls == 1

        old_auth_calls = [
            call for call in fake_session.request_calls
            if call["headers"].get("Authorization") == "Bearer old-access"
        ]
        new_auth_calls = [
            call for call in fake_session.request_calls
            if call["headers"].get("Authorization") == "Bearer new-access"
        ]
        assert len(old_auth_calls) == 2
        assert len(new_auth_calls) == 2

        await client.close()

    asyncio.run(scenario())


def test_http_client_ignores_stale_refresh_result_after_tokens_change() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("old-access", "old-refresh")

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        class DelayedRefreshResponse(FakeResponse):
            async def json(self) -> dict:
                refresh_started.set()
                await release_refresh.wait()
                return {
                    "data": {
                        "access_token": "late-old-access",
                        "refresh_token": "late-old-refresh",
                    }
                }

        fake_session = FakeSession(
            post_handler=lambda **_kwargs: DelayedRefreshResponse(200),
        )
        client._session = fake_session

        refresh_task = asyncio.create_task(client._refresh_access_token())
        await refresh_started.wait()

        client.clear_tokens()
        client.set_tokens("new-access", "new-refresh")
        release_refresh.set()

        assert await refresh_task is False
        assert client.access_token == "new-access"
        assert client.refresh_token == "new-refresh"

        await client.close()

    asyncio.run(scenario())


def test_http_client_upload_file_internal_401_retries_after_refresh() -> None:
    async def scenario() -> None:
        file_path = _write_upload_fixture("upload-internal.bin")
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("old-access", "refresh-token")

        refresh_calls = 0

        async def fake_perform_refresh(*_args) -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            await asyncio.sleep(0.01)
            client.set_tokens("new-access", "refresh-token-2")
            return True

        client._perform_token_refresh = fake_perform_refresh  # type: ignore[method-assign]

        def post_handler(**call) -> FakeResponse:
            authorization = call["headers"].get("Authorization")
            if authorization == "Bearer old-access":
                return FakeResponse(401, {"message": "token expired"})
            if authorization == "Bearer new-access":
                return FakeResponse(201, {"data": {"url": "/uploads/demo.bin", "file_type": "application/octet-stream"}})
            return FakeResponse(500, {"message": f"unexpected auth header: {authorization}"})

        fake_session = FakeSession(post_handler=post_handler)
        client._session = fake_session

        payload = await client.upload_file(str(file_path), upload_path="/files/upload")

        assert payload["url"] == "/uploads/demo.bin"
        assert refresh_calls == 1
        assert [call["headers"].get("Authorization") for call in fake_session.post_calls] == [
            "Bearer old-access",
            "Bearer new-access",
        ]

        await client.close()

    asyncio.run(scenario())



def test_http_client_upload_file_defaults_to_files_upload_endpoint() -> None:
    async def scenario() -> None:
        file_path = _write_upload_fixture("upload-default.bin")
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("app-access", "refresh-token")

        fake_session = FakeSession(
            post_handler=lambda **_kwargs: FakeResponse(201, {"data": {"url": "/uploads/default.bin", "file_type": "application/octet-stream"}}),
        )
        client._session = fake_session

        payload = await client.upload_file(str(file_path))

        assert payload["url"] == "/uploads/default.bin"
        assert fake_session.post_calls[0]["url"] == "http://app.local/api/v1/files/upload"

        await client.close()

    asyncio.run(scenario())


def test_http_client_refresh_rejection_notifies_auth_loss_once() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("old-access", "bad-refresh")
        auth_loss_reasons: list[str] = []
        client.add_auth_loss_listener(auth_loss_reasons.append)

        fake_session = FakeSession(
            request_handler=lambda **_kwargs: FakeResponse(401, {"message": "token expired"}),
            post_handler=lambda **_kwargs: FakeResponse(401, {"message": "refresh rejected"}),
        )
        client._session = fake_session

        with pytest.raises(AuthExpiredError):
            await client.get("/profile")

        assert auth_loss_reasons == ["refresh_rejected"]
        assert client.access_token is None
        assert client.refresh_token is None

        await client.close()

    asyncio.run(scenario())



def test_http_client_upload_file_absolute_url_skips_app_auth_and_refresh() -> None:
    async def scenario() -> None:
        file_path = _write_upload_fixture("upload-external.bin")
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("app-access", "refresh-token")

        refresh_calls = 0

        async def fake_refresh() -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            return True

        client._refresh_access_token = fake_refresh  # type: ignore[method-assign]
        fake_session = FakeSession(
            post_handler=lambda **_kwargs: FakeResponse(401, {"message": "bad upload token", "code": 40191}),
        )
        client._session = fake_session

        with pytest.raises(APIError) as exc_info:
            await client.upload_file(str(file_path), upload_path="https://uploads.example.com/file")

        assert exc_info.value.message == "bad upload token"
        assert exc_info.value.status_code == 401
        assert refresh_calls == 0
        assert fake_session.post_calls[0]["url"] == "https://uploads.example.com/file"
        assert "Authorization" not in fake_session.post_calls[0]["headers"]

        await client.close()

    asyncio.run(scenario())


def test_http_client_stream_lines_absolute_url_skips_base_url_and_app_auth() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("app-access", "refresh-token")

        fake_session = FakeSession(
            request_handler=lambda **_kwargs: FakeStreamResponse(200, ["line-1", "", "line-2"]),
        )
        client._session = fake_session

        lines = [
            line async for line in client.stream_lines(
                "POST",
                "http://localhost:11434/api/chat",
                json={"message": "hello"},
            )
        ]

        assert lines == ["line-1", "line-2"]
        assert len(fake_session.request_calls) == 1
        call = fake_session.request_calls[0]
        assert call["url"] == "http://localhost:11434/api/chat"
        assert "Authorization" not in call["headers"]

        await client.close()

    asyncio.run(scenario())


def test_http_client_stream_lines_internal_401_retries_after_refresh() -> None:
    async def scenario() -> None:
        client = HTTPClient(base_url="http://app.local/api/v1")
        client.set_tokens("old-access", "refresh-token")

        refresh_calls = 0

        async def fake_perform_refresh(*_args) -> bool:
            nonlocal refresh_calls
            refresh_calls += 1
            client.set_tokens("new-access", "refresh-token-2")
            return True

        client._perform_token_refresh = fake_perform_refresh  # type: ignore[method-assign]

        def request_handler(**call):
            authorization = call["headers"].get("Authorization")
            if authorization == "Bearer old-access":
                return FakeStreamResponse(401, [], payload={"message": "token expired"})
            if authorization == "Bearer new-access":
                return FakeStreamResponse(200, ["retry-ok"])
            return FakeStreamResponse(500, [], payload={"message": f"unexpected auth header: {authorization}"})

        fake_session = FakeSession(request_handler=request_handler)
        client._session = fake_session

        lines = [line async for line in client.stream_lines("GET", "/stream")]

        assert lines == ["retry-ok"]
        assert refresh_calls == 1
        assert [call["headers"].get("Authorization") for call in fake_session.request_calls] == [
            "Bearer old-access",
            "Bearer new-access",
        ]

        await client.close()

    asyncio.run(scenario())
