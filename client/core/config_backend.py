"""
Configuration Module

后端配置 - 通过环境变量配置，开发者使用
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def _runtime_app_root() -> Path:
    explicit_root = str(os.getenv("ASSISTIM_APP_ROOT", "") or "").strip()
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_ROOT = _runtime_app_root()
CLIENT_ROOT = APP_ROOT / "client"
UI_CONFIG_PATH = (
    Path(str(os.getenv("ASSISTIM_CONFIG_PATH", "") or "")).expanduser().resolve()
    if str(os.getenv("ASSISTIM_CONFIG_PATH", "") or "").strip()
    else APP_ROOT / "data" / "config.json"
)
MODEL_MANIFEST_PATH = CLIENT_ROOT / "resources" / "models" / "manifest.json"
VERSION_FILE_PATH = (
    Path(str(os.getenv("ASSISTIM_VERSION_FILE", "") or "")).expanduser().resolve()
    if str(os.getenv("ASSISTIM_VERSION_FILE", "") or "").strip()
    else APP_ROOT / "version.json"
)

DEFAULT_AI_MODEL_FILE = "gemma-4-E2B-it-Q4_K_M.gguf"
DEFAULT_AI_MODEL_ID = "gemma-4-E2B-it-Q4_K_M"
DEFAULT_AI_MODEL_PATH = CLIENT_ROOT / "resources" / "models" / DEFAULT_AI_MODEL_FILE
DEFAULT_AI_EMBEDDING_MODEL_FILE = "jina-embeddings-v3-Q4_K_M.gguf"
DEFAULT_AI_EMBEDDING_MODEL_ID = "jina-embeddings-v3-Q4_K_M"
DEFAULT_AI_EMBEDDING_MODEL_PATH = CLIENT_ROOT / "resources" / "models" / DEFAULT_AI_EMBEDDING_MODEL_FILE
DEFAULT_LOCAL_SERVER_HOST = "localhost"
DEFAULT_LOCAL_SERVER_PORT = 8000
DEFAULT_DB_PATH = "data/assistim.db"
DEFAULT_DB_ENCRYPTION_MODE = "plain"
DEFAULT_DB_ENCRYPTION_PROVIDER = "auto"
SUPPORTED_DB_ENCRYPTION_MODES = {"plain", "sqlcipher"}
SUPPORTED_DB_ENCRYPTION_PROVIDERS = {"auto", "sqlite-default", "sqlcipher-compatible"}
DEFAULT_VERSION_INFO: dict[str, str] = {
    "app": "AssistIM",
    "version": "0.1.0",
    "channel": "test",
    "platform": "win64",
}


def is_development_runtime() -> bool:
    """Return whether developer-only runtime settings should be available."""
    explicit_value = _parse_optional_bool_env("ASSISTIM_DEVELOPER_SETTINGS")
    if explicit_value is not None:
        return explicit_value
    return not getattr(sys, "frozen", False)


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


def _parse_bool_env(name: str, default: bool = False) -> bool:
    """Parse a boolean-like environment variable."""
    raw_value = str(os.getenv(name, "") or "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_optional_bool_env(name: str) -> Optional[bool]:
    """Parse an optional boolean-like environment variable."""
    raw_value = str(os.getenv(name, "") or "").strip().lower()
    if not raw_value:
        return None
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_int_env(name: str, default: int) -> int:
    """Parse one integer environment variable with fallback."""
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _parse_int_value(raw_value: Any, default: int) -> int:
    """Parse one integer-like value with fallback."""
    if raw_value is None:
        return default
    try:
        return int(str(raw_value).strip())
    except ValueError:
        return default


def _parse_float_env(name: str, default: float) -> float:
    """Parse one float environment variable with fallback."""
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _parse_gpu_layers_env(name: str, default: int) -> int:
    """Parse llama.cpp GPU layer count, accepting 'auto' as -1."""
    raw_value = str(os.getenv(name, "") or "").strip().lower()
    if not raw_value:
        return default
    if raw_value == "auto":
        return -1
    try:
        return int(raw_value)
    except ValueError:
        return default


def _load_ui_config_payload() -> dict[str, Any]:
    """Load the UI config file when it exists."""
    try:
        payload = json.loads(UI_CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _ui_config_value(group: str, name: str, default: Any = None) -> Any:
    payload = _load_ui_config_payload()
    section = payload.get(group)
    if not isinstance(section, dict):
        return default
    return section.get(name, default)


def _ui_config_has_value(group: str, name: str) -> bool:
    payload = _load_ui_config_payload()
    section = payload.get(group)
    return isinstance(section, dict) and name in section


def _manifest_model_path_for_id(model_id: str) -> Optional[Path]:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return None
    try:
        payload = json.loads(MODEL_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    for item in list(payload.get("models") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("model_id") or "").strip() != normalized_model_id:
            continue
        file_name = str(item.get("file_name") or "").strip()
        if not file_name:
            return None
        return CLIENT_ROOT / "resources" / "models" / file_name
    return None


def _resolve_ui_ai_model_id() -> str:
    configured_model_id = str(_ui_config_value("AI", "ModelId", DEFAULT_AI_MODEL_ID) or "").strip()
    if configured_model_id and _manifest_model_path_for_id(configured_model_id) is not None:
        return configured_model_id
    return DEFAULT_AI_MODEL_ID


def _resolve_ai_model_id() -> str:
    if _ui_config_has_value("AI", "ModelId"):
        return _resolve_ui_ai_model_id()
    explicit_model_id = str(os.getenv("ASSISTIM_AI_MODEL_ID", "") or "").strip()
    if explicit_model_id:
        return explicit_model_id
    return _resolve_ui_ai_model_id()


def _resolve_ai_model_path() -> str:
    if _ui_config_has_value("AI", "ModelId"):
        selected_model_path = _manifest_model_path_for_id(_resolve_ui_ai_model_id())
        if selected_model_path is not None:
            return str(selected_model_path)
    explicit_model_path = str(os.getenv("ASSISTIM_AI_MODEL_PATH", "") or "").strip()
    if explicit_model_path:
        return explicit_model_path
    explicit_model_id = str(os.getenv("ASSISTIM_AI_MODEL_ID", "") or "").strip()
    explicit_selected_model_path = _manifest_model_path_for_id(explicit_model_id)
    if explicit_selected_model_path is not None:
        return str(explicit_selected_model_path)
    selected_model_path = _manifest_model_path_for_id(_resolve_ui_ai_model_id())
    if selected_model_path is not None:
        return str(selected_model_path)
    return str(DEFAULT_AI_MODEL_PATH)


def _resolve_ai_gpu_enabled() -> bool:
    if _ui_config_has_value("AI", "GpuAccelerationEnabled"):
        return _parse_bool_ui_config_value("AI", "GpuAccelerationEnabled", True)
    explicit_gpu_enabled = _parse_optional_bool_env("ASSISTIM_AI_GPU_ENABLED")
    if explicit_gpu_enabled is not None:
        return explicit_gpu_enabled
    return _parse_bool_ui_config_value("AI", "GpuAccelerationEnabled", True)


def _default_embedding_model_path_for_id(model_id: str) -> str:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return str(DEFAULT_AI_EMBEDDING_MODEL_PATH)
    return str(CLIENT_ROOT / "resources" / "models" / f"{normalized_model_id}.gguf")


def _resolve_ai_embedding_model_id() -> str:
    explicit_model_id = str(os.getenv("ASSISTIM_AI_EMBEDDING_MODEL_ID", "") or "").strip()
    if explicit_model_id:
        return explicit_model_id
    return DEFAULT_AI_EMBEDDING_MODEL_ID


def _resolve_ai_embedding_model_path() -> str:
    explicit_model_path = str(os.getenv("ASSISTIM_AI_EMBEDDING_MODEL_PATH", "") or "").strip()
    if explicit_model_path:
        return explicit_model_path
    explicit_model_id = str(os.getenv("ASSISTIM_AI_EMBEDDING_MODEL_ID", "") or "").strip()
    if explicit_model_id:
        return _default_embedding_model_path_for_id(explicit_model_id)
    return str(DEFAULT_AI_EMBEDDING_MODEL_PATH)


def _parse_bool_ui_config_value(group: str, name: str, default: bool) -> bool:
    raw_value = _ui_config_value(group, name, default)
    if isinstance(raw_value, bool):
        return raw_value
    normalized = str(raw_value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_server_use_localhost() -> bool:
    if not is_development_runtime():
        return False
    return _parse_bool_ui_config_value("Server", "UseLocalhost", False)


def _resolve_server_host() -> str:
    explicit_host = str(os.getenv("ASSISTIM_HOST", "") or "").strip()
    if explicit_host:
        return explicit_host
    if _resolve_server_use_localhost():
        return DEFAULT_LOCAL_SERVER_HOST
    configured_host = str(_ui_config_value("Server", "Host", "localhost") or "").strip()
    return configured_host or "localhost"


def _resolve_server_port() -> int:
    explicit_port = str(os.getenv("ASSISTIM_PORT", "") or "").strip()
    if explicit_port:
        return _parse_int_env("ASSISTIM_PORT", 8000)
    if _resolve_server_use_localhost():
        return DEFAULT_LOCAL_SERVER_PORT
    return _parse_int_value(_ui_config_value("Server", "Port", 8000), 8000)


def _resolve_server_use_ssl() -> bool:
    explicit_use_ssl = _parse_optional_bool_env("ASSISTIM_USE_SSL")
    if explicit_use_ssl is not None:
        return explicit_use_ssl
    if _resolve_server_use_localhost():
        return False
    return _parse_bool_ui_config_value("Server", "UseSsl", False)


def _normalize_config_choice(value: Any, supported_values: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in supported_values else default


def _resolve_storage_db_path() -> str:
    explicit_path = str(os.getenv("ASSISTIM_DB_PATH", "") or "").strip()
    if explicit_path:
        return explicit_path
    configured_path = str(_ui_config_value("Storage", "DbPath", DEFAULT_DB_PATH) or "").strip()
    return configured_path or DEFAULT_DB_PATH


def _resolve_storage_db_encryption_mode() -> str:
    explicit_mode = str(os.getenv("ASSISTIM_DB_ENCRYPTION_MODE", "") or "").strip()
    if explicit_mode:
        return _normalize_config_choice(
            explicit_mode,
            SUPPORTED_DB_ENCRYPTION_MODES,
            DEFAULT_DB_ENCRYPTION_MODE,
        )
    return _normalize_config_choice(
        _ui_config_value("Storage", "DbEncryptionMode", DEFAULT_DB_ENCRYPTION_MODE),
        SUPPORTED_DB_ENCRYPTION_MODES,
        DEFAULT_DB_ENCRYPTION_MODE,
    )


def _resolve_storage_db_encryption_provider() -> str:
    explicit_provider = str(os.getenv("ASSISTIM_DB_ENCRYPTION_PROVIDER", "") or "").strip()
    if explicit_provider:
        return _normalize_config_choice(
            explicit_provider,
            SUPPORTED_DB_ENCRYPTION_PROVIDERS,
            DEFAULT_DB_ENCRYPTION_PROVIDER,
        )
    return _normalize_config_choice(
        _ui_config_value("Storage", "DbEncryptionProvider", DEFAULT_DB_ENCRYPTION_PROVIDER),
        SUPPORTED_DB_ENCRYPTION_PROVIDERS,
        DEFAULT_DB_ENCRYPTION_PROVIDER,
    )


def get_version_info() -> dict[str, str]:
    """Load package version metadata for UI display and packaged releases."""
    info = dict(DEFAULT_VERSION_INFO)
    try:
        payload = json.loads(VERSION_FILE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {}
    if isinstance(payload, dict):
        for key in ("app", "version", "channel", "platform", "build_time", "commit"):
            value = payload.get(key)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                info[key] = normalized
    explicit_version = str(os.getenv("ASSISTIM_APP_VERSION", "") or "").strip()
    if explicit_version:
        info["version"] = explicit_version.lstrip("v")
    return info


def get_app_version() -> str:
    """Return the app version without the UI 'v' prefix."""
    version = str(get_version_info().get("version") or DEFAULT_VERSION_INFO["version"]).strip()
    return version.lstrip("v") or DEFAULT_VERSION_INFO["version"]


@dataclass
class ServerConfig:
    """Server connection configuration."""

    host: str = field(default_factory=_resolve_server_host)
    port: int = field(default_factory=_resolve_server_port)
    use_ssl: bool = field(default_factory=_resolve_server_use_ssl)

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
class NetworkConfig:
    """HTTP request timeout configuration."""

    request_timeout: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_REQUEST_TIMEOUT", "30.0")))
    upload_timeout: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_UPLOAD_TIMEOUT", "300.0")))


@dataclass
class StorageConfig:
    """Local storage configuration."""

    db_path: str = field(default_factory=_resolve_storage_db_path)
    db_encryption_mode: str = field(default_factory=_resolve_storage_db_encryption_mode)
    db_encryption_provider: str = field(default_factory=_resolve_storage_db_encryption_provider)


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
class AIConfig:
    """Local AI runtime configuration."""

    provider: str = field(default_factory=lambda: str(os.getenv("ASSISTIM_AI_PROVIDER", "local_gguf") or "local_gguf").strip().lower())
    model_path: str = field(default_factory=_resolve_ai_model_path)
    model_id: str = field(default_factory=_resolve_ai_model_id)
    context_size: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_AI_CONTEXT_SIZE", 4096))
    max_output_tokens: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_AI_MAX_OUTPUT_TOKENS", 512))
    temperature: float = field(default_factory=lambda: _parse_float_env("ASSISTIM_AI_TEMPERATURE", 0.4))
    gpu_layers: int = field(default_factory=lambda: _parse_gpu_layers_env("ASSISTIM_AI_GPU_LAYERS", 0))
    gpu_enabled: bool = field(default_factory=_resolve_ai_gpu_enabled)
    cpu_threads: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_AI_CPU_THREADS", 0))
    verbose: bool = field(default_factory=lambda: _parse_bool_env("ASSISTIM_AI_VERBOSE", False))
    embedding_model_path: str = field(default_factory=_resolve_ai_embedding_model_path)
    embedding_model_id: str = field(default_factory=_resolve_ai_embedding_model_id)
    embedding_context_size: int = field(default_factory=lambda: _parse_int_env("ASSISTIM_AI_EMBEDDING_CONTEXT_SIZE", 1024))
    embedding_gpu_layers: int = field(default_factory=lambda: _parse_gpu_layers_env("ASSISTIM_AI_EMBEDDING_GPU_LAYERS", 0))


@dataclass
class Config:
    """Main application configuration - 后端配置."""

    server: ServerConfig = field(default_factory=ServerConfig)
    reconnect: ReconnectConfig = field(default_factory=ReconnectConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    webrtc: WebRTCConfig = field(default_factory=WebRTCConfig)
    ai: AIConfig = field(default_factory=AIConfig)

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
