from types import MethodType
from pathlib import Path

from client.ui.controllers.contact_controller import FriendRequestRecord
from client.ui.windows.contact_interface import ContactInterface


def _request(
    request_id: str,
    *,
    sender_id: str,
    receiver_id: str,
    status: str = "pending",
    created_at: str = "2026-05-09T10:00:00Z",
) -> FriendRequestRecord:
    return FriendRequestRecord(
        id=request_id,
        sender_id=sender_id,
        receiver_id=receiver_id,
        status=status,
        created_at=created_at,
        sender_name=f"sender-{request_id}",
        receiver_name=f"receiver-{request_id}",
    )


def test_contact_interface_visible_requests_only_includes_incoming_pending() -> None:
    interface = ContactInterface.__new__(ContactInterface)
    interface._current_user_id = "current-user"
    interface._requests = [
        _request("incoming-pending", sender_id="user-a", receiver_id="current-user", status="pending"),
        _request("outgoing-pending", sender_id="current-user", receiver_id="user-b", status="pending"),
        _request("incoming-accepted", sender_id="user-c", receiver_id="current-user", status="accepted"),
        _request("unknown-pending", sender_id="user-d", receiver_id="user-e", status="pending"),
    ]

    assert [request.id for request in interface._visible_requests()] == ["incoming-pending"]


def test_contact_interface_sent_request_callback_does_not_show_outgoing_item() -> None:
    interface = ContactInterface.__new__(ContactInterface)
    interface._current_user_id = "current-user"
    interface._request_items = {}
    inserted: list[str] = []
    activated_pages: list[str] = []

    def record_upsert(self, request: FriendRequestRecord) -> None:
        inserted.append(request.id)

    def record_activate(self, page: str) -> None:
        activated_pages.append(page)

    interface._upsert_request_record = MethodType(record_upsert, interface)
    interface._activate_page = MethodType(record_activate, interface)
    interface._restore_selection = MethodType(lambda self, full_reload: None, interface)
    interface._update_summary_counts = MethodType(lambda self: None, interface)

    interface._on_friend_request_sent(
        {
            "request": {
                "request_id": "outgoing-1",
                "status": "pending",
                "sender": {"id": "current-user", "username": "me"},
                "receiver": {"id": "target-user", "username": "target"},
            }
        }
    )

    assert inserted == []
    assert activated_pages == []


def test_contact_interface_sidebar_does_not_render_contact_count_summary() -> None:
    source = Path("client/ui/windows/contact_interface.py").read_text(encoding="utf-8")
    contact_interface_block = source.split("class ContactInterface(QWidget):", 1)[1]

    assert "contact.sidebar.summary" not in contact_interface_block
    assert "contactSummaryLabel" not in contact_interface_block
