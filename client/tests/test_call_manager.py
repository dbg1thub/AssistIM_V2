import asyncio

import client.managers.call_manager as call_manager_module
from client.managers.call_manager import CallEvent, CallManager
from client.models.message import Session


class FakeConnectionManager:
    def __init__(self) -> None:
        self.listener = None
        self.sent: list[dict] = []

    def add_message_listener(self, listener) -> None:
        self.listener = listener

    def remove_message_listener(self, listener) -> None:
        if self.listener == listener:
            self.listener = None

    async def send_call_event(self, event_type: str, data: dict, *, msg_id: str = "") -> bool:
        self.sent.append({"type": event_type, "data": dict(data), "msg_id": msg_id})
        return True

    async def dispatch(self, message: dict) -> None:
        assert self.listener is not None
        await self.listener(message)


class FakeEventBus:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, object]] = []

    async def emit(self, event_type: str, data=None) -> None:
        self.emitted.append((event_type, data))


def test_call_manager_starts_direct_call_and_emits_invite(monkeypatch) -> None:
    fake_conn = FakeConnectionManager()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(call_manager_module, "get_connection_manager", lambda: fake_conn)
    monkeypatch.setattr(call_manager_module, "get_event_bus", lambda: fake_event_bus)

    manager = CallManager()
    manager.set_user_id("alice")
    asyncio.run(manager.initialize())

    session = Session(
        session_id="session-1",
        name="Bob",
        session_type="direct",
        participant_ids=["alice", "bob"],
        extra={"counterpart_id": "bob"},
    )

    active_call = asyncio.run(manager.start_call(session, "voice"))

    assert active_call.session_id == "session-1"
    assert active_call.initiator_id == "alice"
    assert active_call.recipient_id == "bob"
    assert fake_conn.sent[0]["type"] == "call_invite"
    assert fake_conn.sent[0]["data"]["session_id"] == "session-1"
    assert fake_event_bus.emitted[0][0] == CallEvent.INVITE_SENT


def test_call_manager_tracks_incoming_invite_accept_and_ice_signal(monkeypatch) -> None:
    fake_conn = FakeConnectionManager()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(call_manager_module, "get_connection_manager", lambda: fake_conn)
    monkeypatch.setattr(call_manager_module, "get_event_bus", lambda: fake_event_bus)

    manager = CallManager()
    manager.set_user_id("bob")
    asyncio.run(manager.initialize())

    invite_payload = {
        "type": "call_invite",
        "data": {
            "call_id": "call-1",
            "session_id": "session-1",
            "initiator_id": "alice",
            "recipient_id": "bob",
            "media_type": "video",
            "status": "invited",
        },
    }
    asyncio.run(fake_conn.dispatch(invite_payload))

    assert manager.active_call is not None
    assert manager.active_call.call_id == "call-1"
    assert manager.active_call.direction == "incoming"
    assert fake_event_bus.emitted[0][0] == CallEvent.INVITE_RECEIVED
    assert asyncio.run(manager.accept_call("call-1")) is True

    accept_payload = {
        "type": "call_accept",
        "data": {
            "call_id": "call-1",
            "session_id": "session-1",
            "initiator_id": "alice",
            "recipient_id": "bob",
            "media_type": "video",
            "status": "accepted",
            "actor_id": "bob",
        },
    }
    asyncio.run(fake_conn.dispatch(accept_payload))

    assert manager.active_call is not None
    assert manager.active_call.status == "accepted"
    assert fake_event_bus.emitted[-1][1]["is_local_media_endpoint"] is True

    signal_payload = {
        "type": "call_ice",
        "data": {
            "call_id": "call-1",
            "actor_id": "alice",
            "candidate": {"candidate": "candidate:1 1 udp 1 127.0.0.1 5000 typ host"},
        },
    }
    asyncio.run(fake_conn.dispatch(signal_payload))

    assert fake_event_bus.emitted[-1][0] == CallEvent.SIGNAL


def test_call_manager_ignores_empty_or_stale_call_payloads(monkeypatch) -> None:
    fake_conn = FakeConnectionManager()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(call_manager_module, "get_connection_manager", lambda: fake_conn)
    monkeypatch.setattr(call_manager_module, "get_event_bus", lambda: fake_event_bus)

    manager = CallManager()
    manager.set_user_id("bob")
    asyncio.run(manager.initialize())

    asyncio.run(fake_conn.dispatch({"type": "call_invite", "data": {"session_id": "session-1"}}))
    assert manager.active_call is None
    assert fake_event_bus.emitted == []

    asyncio.run(
        fake_conn.dispatch(
            {
                "type": "call_invite",
                "data": {
                    "call_id": "call-1",
                    "session_id": "session-1",
                    "initiator_id": "alice",
                    "recipient_id": "bob",
                    "media_type": "voice",
                },
            }
        )
    )
    asyncio.run(fake_conn.dispatch({"type": "call_hangup", "data": {"call_id": "other-call"}}))

    assert manager.active_call is not None
    assert manager.active_call.call_id == "call-1"


def test_call_manager_marks_passive_accepted_mirror_without_starting_media(monkeypatch) -> None:
    fake_conn = FakeConnectionManager()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(call_manager_module, "get_connection_manager", lambda: fake_conn)
    monkeypatch.setattr(call_manager_module, "get_event_bus", lambda: fake_event_bus)

    manager = CallManager()
    manager.set_user_id("bob")
    asyncio.run(manager.initialize())

    asyncio.run(
        fake_conn.dispatch(
            {
                "type": "call_invite",
                "data": {
                    "call_id": "call-passive",
                    "session_id": "session-1",
                    "initiator_id": "alice",
                    "recipient_id": "bob",
                    "media_type": "voice",
                    "status": "invited",
                },
            }
        )
    )
    asyncio.run(
        fake_conn.dispatch(
            {
                "type": "call_accept",
                "data": {
                    "call_id": "call-passive",
                    "session_id": "session-1",
                    "initiator_id": "alice",
                    "recipient_id": "bob",
                    "media_type": "voice",
                    "status": "accepted",
                    "actor_id": "bob",
                },
            }
        )
    )

    assert fake_event_bus.emitted[-1][0] == CallEvent.ACCEPTED
    assert fake_event_bus.emitted[-1][1]["is_local_media_endpoint"] is False
    assert manager.active_call is None


def test_call_manager_times_out_unanswered_outgoing_call(monkeypatch) -> None:
    fake_conn = FakeConnectionManager()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(call_manager_module, "get_connection_manager", lambda: fake_conn)
    monkeypatch.setattr(call_manager_module, "get_event_bus", lambda: fake_event_bus)

    async def scenario() -> None:
        manager = CallManager()
        manager.UNANSWERED_TIMEOUT_SECONDS = 0.01
        manager.set_user_id("alice")
        await manager.initialize()

        session = Session(
            session_id="session-1",
            name="Bob",
            session_type="direct",
            participant_ids=["alice", "bob"],
            extra={"counterpart_id": "bob"},
        )

        await manager.start_call(session, "voice")
        await asyncio.sleep(0.05)

        assert fake_conn.sent[-1]["type"] == "call_hangup"
        assert fake_conn.sent[-1]["data"]["reason"] == "timeout"

        await manager.close()

    asyncio.run(scenario())


def test_call_manager_close_clears_authenticated_user_context(monkeypatch) -> None:
    fake_conn = FakeConnectionManager()
    fake_event_bus = FakeEventBus()

    monkeypatch.setattr(call_manager_module, "get_connection_manager", lambda: fake_conn)
    monkeypatch.setattr(call_manager_module, "get_event_bus", lambda: fake_event_bus)

    async def scenario() -> None:
        manager = CallManager()
        manager.set_user_id("alice")
        await manager.initialize()
        manager._timing_origins["call-1"] = 123.0
        await manager.close()

        assert manager._user_id == ""
        assert manager._timing_origins == {}
        assert fake_conn.listener is None

    asyncio.run(scenario())
