from __future__ import annotations

import asyncio
from concurrent.futures import Future

import pytest

from client.network.websocket_client import ConnectionState, WebSocketClient


class _Signals:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear_callbacks(self) -> None:
        self.clear_calls += 1


class _AliveThread:
    def __init__(self) -> None:
        self.join_calls: list[float | None] = []

    def is_alive(self) -> bool:
        return True

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)


class _DeadLoop:
    def is_running(self) -> bool:
        return False


def _client_without_init(**overrides):
    client = object.__new__(WebSocketClient)
    defaults = {
        "url": "ws://example.test/ws",
        "heartbeat_interval": 30.0,
        "heartbeat_timeout": 10.0,
        "max_reconnect_attempts": 10,
        "initial_reconnect_delay": 1.0,
        "max_reconnect_delay": 30.0,
        "reconnect_backoff_factor": 2.0,
        "_state": ConnectionState.DISCONNECTED,
        "_ws": None,
        "_intentional_disconnect": False,
        "_main_loop": None,
        "_thread_loop": None,
        "_thread": None,
        "_connect_task": None,
        "_connect_future": None,
        "_receive_task": None,
        "_heartbeat_task": None,
        "_reconnect_task": None,
        "_on_connect": None,
        "_on_disconnect": None,
        "_on_message": None,
        "_on_error": None,
        "signals": None,
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        setattr(client, name, value)
    return client


def test_websocket_close_cancels_connect_future_and_clears_signal_queue() -> None:
    connect_future: Future = Future()
    signals = _Signals()
    client = _client_without_init(_connect_future=connect_future, signals=signals)

    async def scenario() -> None:
        await client.close()

    asyncio.run(scenario())

    assert connect_future.cancelled() is True
    assert client._connect_future is None
    assert signals.clear_calls == 1
    assert client._on_message is None


def test_websocket_close_keeps_stuck_worker_thread_reference() -> None:
    thread = _AliveThread()
    client = _client_without_init(_thread=thread)

    async def scenario() -> None:
        await client.close()

    asyncio.run(scenario())

    assert thread.join_calls == [2.0]
    assert client._thread is thread


def test_websocket_worker_loop_refuses_to_replace_stuck_thread() -> None:
    client = _client_without_init(_thread=_AliveThread(), _thread_loop=_DeadLoop())

    with pytest.raises(RuntimeError, match="did not stop cleanly"):
        client._ensure_worker_loop()