"""Seed data tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.seed import DEMO_PASSWORD, seed_demo_data


def test_seed_demo_data_is_idempotent() -> None:
    seed_root = Path(__file__).resolve().parents[1] / ".testdata" / "seed-check"
    if seed_root.exists():
        shutil.rmtree(seed_root)
    seed_root.mkdir(parents=True, exist_ok=True)

    database_url = f"sqlite:///{(seed_root / 'seed.db').as_posix()}"
    upload_dir = seed_root / "uploads"

    first_summary = seed_demo_data(database_url=database_url, upload_dir=str(upload_dir), reset=True)
    second_summary = seed_demo_data(database_url=database_url, upload_dir=str(upload_dir), reset=False)

    assert first_summary["counts"] == second_summary["counts"]
    assert first_summary["counts"] == {
        "users": 4,
        "friend_requests": 1,
        "friendships": 4,
        "sessions": 2,
        "messages": 5,
        "groups": 1,
        "moments": 2,
        "files": 1,
    }
    assert second_summary["demo_password"] == DEMO_PASSWORD
    assert (upload_dir / "seed-demo-note.txt").exists()
