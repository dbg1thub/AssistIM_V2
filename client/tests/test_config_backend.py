from __future__ import annotations

from client.core.config_backend import ServerConfig


def test_server_config_uses_canonical_api_v1_base_url() -> None:
    config = ServerConfig(host="example.test", port=8443, use_ssl=True)

    assert config.origin_url == "https://example.test:8443"
    assert config.api_base_url == "https://example.test:8443/api/v1"
    assert config.ws_url == "wss://example.test:8443/ws"