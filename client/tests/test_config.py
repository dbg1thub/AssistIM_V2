from __future__ import annotations

import json
from pathlib import Path

from client.core import config as config_module


def test_merge_config_payload_preserves_unknown_sections() -> None:
    existing_payload = {
        "Server": {
            "Host": "47.83.139.108",
            "Port": 80,
            "UseSsl": False,
        },
        "AI": {
            "ModelId": "gemma-4-E2B-it-Q4_K_M",
            "RuntimeProvider": "local_gguf",
        },
    }
    updated_payload = {
        "AI": {
            "GpuAccelerationEnabled": False,
        },
        "Theme": {
            "ThemeMode": "Dark",
        },
    }

    merged_payload = config_module._merge_config_payload(existing_payload, updated_payload)

    assert merged_payload["Server"] == existing_payload["Server"]
    assert merged_payload["AI"] == {
        "ModelId": "gemma-4-E2B-it-Q4_K_M",
        "RuntimeProvider": "local_gguf",
        "GpuAccelerationEnabled": False,
    }
    assert merged_payload["Theme"] == {"ThemeMode": "Dark"}


def test_cfg_save_preserves_server_settings(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "Server": {
            "Host": "47.83.139.108",
            "Port": 80,
            "UseSsl": false
          },
          "AI": {
            "RuntimeProvider": "local_gguf"
          }
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module.cfg, "file", config_path)
    monkeypatch.setattr(
        config_module.cfg,
        "toDict",
        lambda serialize=True: {
            "AI": {
                "GpuAccelerationEnabled": False,
            },
            "Theme": {
                "ThemeMode": "Dark",
            },
        },
    )

    config_module.cfg.save()

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["Server"] == {
        "Host": "47.83.139.108",
        "Port": 80,
        "UseSsl": False,
    }
    assert payload["AI"] == {
        "RuntimeProvider": "local_gguf",
        "GpuAccelerationEnabled": False,
    }
    assert payload["Theme"] == {"ThemeMode": "Dark"}


def test_qconfig_auto_save_preserves_server_settings(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "Server": {
            "Host": "47.83.139.108",
            "Port": 80,
            "UseSsl": false
          },
          "AI": {
            "RuntimeProvider": "local_gguf"
          }
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module.cfg, "file", config_path)
    monkeypatch.setattr(
        config_module.cfg,
        "toDict",
        lambda serialize=True: {
            "AI": {
                "GpuAccelerationEnabled": False,
            },
            "Theme": {
                "ThemeMode": "Dark",
            },
        },
    )
    original_theme = config_module.cfg.get(config_module.cfg.themeMode)
    target_theme = (
        config_module.Theme.DARK
        if original_theme != config_module.Theme.DARK
        else config_module.Theme.LIGHT
    )

    try:
        config_module.qconfig.set(config_module.cfg.themeMode, target_theme)
    finally:
        config_module.qconfig.set(config_module.cfg.themeMode, original_theme, save=False)

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["Server"] == {
        "Host": "47.83.139.108",
        "Port": 80,
        "UseSsl": False,
    }
    assert payload["AI"] == {
        "RuntimeProvider": "local_gguf",
        "GpuAccelerationEnabled": False,
    }
    assert payload["Theme"] == {"ThemeMode": "Dark"}


def test_cfg_save_seeds_runtime_server_settings_when_missing(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
        {
          "AI": {
            "RuntimeProvider": "local_gguf"
          }
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module.cfg, "file", config_path)
    monkeypatch.setattr(
        config_module.cfg,
        "toDict",
        lambda serialize=True: {
            "AI": {
                "GpuAccelerationEnabled": False,
            }
        },
    )
    monkeypatch.setattr(
        config_module,
        "_runtime_server_payload",
        lambda: {
            "Host": "47.83.139.108",
            "Port": 80,
            "UseSsl": False,
        },
    )

    config_module.cfg.save()

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["Server"] == {
        "Host": "47.83.139.108",
        "Port": 80,
        "UseSsl": False,
    }
    assert payload["AI"] == {
        "RuntimeProvider": "local_gguf",
        "GpuAccelerationEnabled": False,
    }
