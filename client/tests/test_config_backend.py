from __future__ import annotations

from client.core.config_backend import ServerConfig, reload_config


def test_server_config_uses_canonical_api_v1_base_url() -> None:
    config = ServerConfig(host="example.test", port=8443, use_ssl=True)

    assert config.origin_url == "https://example.test:8443"
    assert config.api_base_url == "https://example.test:8443/api/v1"
    assert config.ws_url == "wss://example.test:8443/ws"


def test_webrtc_config_builds_structured_ice_servers(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTIM_WEBRTC_ICE_SERVER_URLS", "stun:legacy.example.org:3478")
    monkeypatch.setenv("ASSISTIM_WEBRTC_STUN_URLS", "stun:stun1.example.org:3478,stun:stun2.example.org:3478")
    monkeypatch.setenv("ASSISTIM_WEBRTC_TURN_URLS", "turn:turn.example.org:3478?transport=udp,turns:turn.example.org:5349")
    monkeypatch.setenv("ASSISTIM_WEBRTC_TURN_USERNAME", "assistim")
    monkeypatch.setenv("ASSISTIM_WEBRTC_TURN_CREDENTIAL", "secret")

    config = reload_config()

    assert config.webrtc.ice_servers == [
        {"urls": ["stun:legacy.example.org:3478"]},
        {"urls": ["stun:stun1.example.org:3478", "stun:stun2.example.org:3478"]},
        {
            "urls": ["turn:turn.example.org:3478?transport=udp", "turns:turn.example.org:5349"],
            "username": "assistim",
            "credential": "secret",
        },
    ]
