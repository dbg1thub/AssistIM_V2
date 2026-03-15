"""
Configuration Module

Centralized configuration management with environment variable support.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ServerConfig:
    """Server connection configuration."""
    
    host: str = field(default_factory=lambda: os.getenv("ASSISTIM_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_PORT", "8000")))
    use_ssl: bool = field(default_factory=lambda: os.getenv("ASSISTIM_USE_SSL", "false").lower() == "true")
    
    @property
    def api_base_url(self) -> str:
        """Get API base URL."""
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.host}:{self.port}/api"
    
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
class AIConfig:
    """AI service configuration."""
    
    provider: str = field(default_factory=lambda: os.getenv("ASSISTIM_AI_PROVIDER", "openai"))
    model: str = field(default_factory=lambda: os.getenv("ASSISTIM_AI_MODEL", "gpt-3.5-turbo"))
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("ASSISTIM_AI_API_KEY"))
    base_url: str = field(default_factory=lambda: os.getenv("ASSISTIM_AI_BASE_URL", "https://api.openai.com/v1"))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("ASSISTIM_AI_MAX_TOKENS", "2048")))
    temperature: float = field(default_factory=lambda: float(os.getenv("ASSISTIM_AI_TEMPERATURE", "0.7")))


@dataclass
class StorageConfig:
    """Local storage configuration."""
    
    db_path: str = field(default_factory=lambda: os.getenv("ASSISTIM_DB_PATH", "data/assistim.db"))


@dataclass
class Config:
    """Main application configuration."""
    
    server: ServerConfig = field(default_factory=ServerConfig)
    reconnect: ReconnectConfig = field(default_factory=ReconnectConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    
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
