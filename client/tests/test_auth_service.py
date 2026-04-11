from __future__ import annotations

import asyncio

from client.services import auth_service as auth_service_module


class FakeHttpClient:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []

    async def post(self, path: str, json=None, **kwargs):
        self.post_calls.append(
            {
                "path": path,
                "json": dict(json or {}),
                "kwargs": dict(kwargs or {}),
            }
        )
        return {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "user": {"id": "user-1"},
        }


def test_auth_service_login_and_register_do_not_inherit_existing_app_auth(monkeypatch) -> None:
    fake_http = FakeHttpClient()
    monkeypatch.setattr(auth_service_module, "get_http_client", lambda: fake_http)

    async def scenario() -> None:
        service = auth_service_module.AuthService()

        await service.login("alice", "secret", force=True)
        await service.register("bob", "Bob", "secret")

        assert fake_http.post_calls == [
            {
                "path": "/auth/login",
                "json": {
                    "username": "alice",
                    "password": "secret",
                    "force": True,
                },
                "kwargs": {
                    "use_auth": False,
                    "retry_on_401": False,
                },
            },
            {
                "path": "/auth/register",
                "json": {
                    "username": "bob",
                    "password": "secret",
                    "nickname": "Bob",
                },
                "kwargs": {
                    "use_auth": False,
                    "retry_on_401": False,
                },
            },
        ]

    asyncio.run(scenario())
