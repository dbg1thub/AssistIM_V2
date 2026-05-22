from pathlib import Path
import re


def _protocol_force_logout_reasons() -> set[str]:
    protocol = Path("docs/protocols/realtime_protocol.md").read_text(encoding="utf-8")
    section = protocol.split("`force_logout.data.reason` 当前枚举：", 1)[1].split("账号策略是单活跃客户端会话", 1)[0]
    return {
        match.group(1)
        for match in re.finditer(r"^- `([^`]+)`", section, flags=re.MULTILINE)
    }


def test_server_force_logout_reasons_match_realtime_protocol() -> None:
    from app.realtime.force_logout_reasons import FORMAL_FORCE_LOGOUT_REASONS

    assert FORMAL_FORCE_LOGOUT_REASONS == _protocol_force_logout_reasons()


def test_force_logout_payload_uses_formal_reason() -> None:
    from app.realtime.force_logout_reasons import (
        FORCE_LOGOUT_REASON_SESSION_REPLACED,
        force_logout_payload,
    )

    payload = force_logout_payload(FORCE_LOGOUT_REASON_SESSION_REPLACED)
    assert payload["type"] == "force_logout"
    assert payload["data"] == {"reason": "session_replaced"}


def test_auth_and_admin_routes_reference_force_logout_reason_constants() -> None:
    auth_source = Path("server/app/api/v1/auth.py").read_text(encoding="utf-8")
    admin_source = Path("server/app/api/v1/admin.py").read_text(encoding="utf-8")

    assert "FORCE_LOGOUT_REASON_SESSION_REPLACED" in auth_source
    assert "FORCE_LOGOUT_REASON_LOGOUT" in auth_source
    assert "FORCE_LOGOUT_REASON_PASSWORD_RESET" in auth_source
    assert "FORCE_LOGOUT_REASON_ADMIN_DISABLE_USER" in admin_source
    assert "FORCE_LOGOUT_REASON_ADMIN_FORCE_LOGOUT" in admin_source
