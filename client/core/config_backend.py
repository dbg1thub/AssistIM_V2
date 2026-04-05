"""
Configuration Module

后端配置 - 通过环境变量配置，开发者使用
"""

import os
from dataclasses import dataclass, field
from typing import Any, Optional


def _parse_webrtc_ice_server_urls() -> list[str]:
    """Parse one comma-separated ICE server URL list from the environment."""
    raw_value = str(os.getenv("ASSISTIM_WEBRTC_ICE_SERVER_URLS", "") or "").strip()
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _parse_csv_env(name: str) -> list[str]:
    """Parse one comma-separated environment variable into a clean list."""
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass
class ServerConfig:
    """Server connection configuration."""

    host: str = field(default_factory=lambda: os.getenv("ASSISTIM_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_PORT", "8000")))
    use_ssl: bool = field(default_factory=lambda: os.getenv("ASSISTIM_USE_SSL", "false").lower() == "true")

    @property
    def origin_url(self) -> str:
        """Get the server origin URL without one API prefix."""
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.host}:{self.port}"

    @property
    def api_base_url(self) -> str:
        """Get the canonical API base URL."""
        return f"{self.origin_url}/api/v1"

    @property
    def ws_url(self) -> str:
        """Get WebSocket URL."""
        scheme = "wss" if self.use_ssl else "ws"
        return f"{scheme}://{self.host}:{self.port}/ws"


@dataclass
class ReconnectConfig:
    """WebSocket reconnection configuration."""

    max_attempts: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_RECONNECT_MAX_ATTEMPTS", "10")))
    initial_delay: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_RECONNECT_INITIAL_DELAY", "1.0")))
    max_delay: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_RECONNECT_MAX_DELAY", "30.0")))
    backoff_factor: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_RECONNECT_BACKOFF_FACTOR", "2.0")))


@dataclass
class HeartbeatConfig:
    """WebSocket heartbeat configuration."""

    interval: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_HEARTBEAT_INTERVAL", "30.0")))
    timeout: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_HEARTBEAT_TIMEOUT", "10.0")))


@dataclass
class StorageConfig:
    """Local storage configuration."""

    db_path: str = field(default_factory=lambda: os.getenv("ASSISTIM_DB_PATH", "data/assistim.db"))
    db_encryption_mode: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_DB_ENCRYPTION_MODE", "plain") or "plain").strip().lower())
    db_encryption_provider: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_DB_ENCRYPTION_PROVIDER", "auto") or "auto").strip().lower())


@dataclass
class WebRTCConfig:
    """WebRTC runtime configuration."""

    ice_server_urls: list[str] = field(default_factory=_parse_webrtc_ice_server_urls)
    stun_urls: list[str] = field(default_factory=lambda: _parse_csv_env("ASSISTIM_WEBRTC_STUN_URLS"))
    turn_urls: list[str] = field(default_factory=lambda: _parse_csv_env("ASSISTIM_WEBRTC_TURN_URLS"))
    turn_username: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_WEBRTC_TURN_USERNAME", "") or "").strip())
    turn_credential: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_WEBRTC_TURN_CREDENTIAL", "") or "").strip())

    @property
    def ice_servers(self) -> list[dict[str, Any]]:
        """Return structured ICE server definitions with optional TURN auth."""
        servers: list[dict[str, Any]] = []
        seen: set[tuple[tuple[str, ...], str, str]] = set()

        def add_server(urls: list[str], *, username: str = "", credential: str = "") -> None:
            normalized_urls = tuple(str(url or "").strip() for url in urls if str(url or "").strip())
            if not normalized_urls:
                return
            key = (normalized_urls, str(username or "").strip(), str(credential or "").strip())
            if key in seen:
                return
            seen.add(key)
            payload: dict[str, Any] = {"urls": list(normalized_urls)}
            if username:
                payload["username"] = username
            if credential:
                payload["credential"] = credential
            servers.append(payload)

        add_server(self.ice_server_urls)
        add_server(self.stun_urls)
        add_server(self.turn_urls, username=self.turn_username, credential=self.turn_credential)
        return servers


@dataclass
class Config:
    """Main application configuration - 后端配置."""

    server: ServerConfig = field(default_factory=ServerConfig)
    reconnect: ReconnectConfig = field(default_factory=ReconnectConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    webrtc: WebRTCConfig = field(default_factory=WebRTCConfig)

    debug: bool = field(default_factory=lambda: os.getenv("ASSISTIM_DEBUG", "false").lower() == "true")


_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment variables."""
    global _config
    _config = Config()
    return _config
