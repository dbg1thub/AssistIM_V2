"""Helpers for profile-related option values and display text."""

from __future__ import annotations

from datetime import date
from typing import Any

from PySide6.QtCore import QDate

from client.core.i18n import tr


PROFILE_GENDER_VALUES = ("female", "male", "non_binary", "other")
PROFILE_STATUS_VALUES = ("online", "busy", "away", "invisible", "offline")


def normalize_profile_choice(value: Any) -> str:
    """Normalize one profile choice value into a canonical lowercase string."""
    return str(value or "").strip().lower()


def profile_gender_options(*, include_blank: bool = True) -> list[tuple[str, str]]:
    """Return the localized gender options used by the profile UI."""
    items: list[tuple[str, str]] = []
    if include_blank:
        items.append(("", tr("profile.option.unspecified", "Unspecified")))
    items.extend(
        (value, tr(f"profile.option.gender.{value}", value.replace("_", " ").title()))
        for value in PROFILE_GENDER_VALUES
    )
    return items


def profile_status_options() -> list[tuple[str, str]]:
    """Return the localized status options used by the profile UI."""
    return [
        (value, tr(f"profile.option.status.{value}", value.replace("_", " ").title()))
        for value in PROFILE_STATUS_VALUES
    ]


def localize_profile_gender(value: Any, *, default: str = "") -> str:
    """Convert one canonical gender value into localized display text."""
    normalized = normalize_profile_choice(value)
    if not normalized:
        return default
    return tr(f"profile.option.gender.{normalized}", normalized.replace("_", " ").title())


def localize_profile_status(value: Any, *, default: str = "") -> str:
    """Convert one canonical status value into localized display text."""
    normalized = normalize_profile_choice(value)
    if not normalized:
        return default
    return tr(f"profile.option.status.{normalized}", normalized.replace("_", " ").title())


def parse_profile_birthday(value: Any) -> date | None:
    """Parse one birthday value from ISO text or date-like input."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


def format_profile_birthday(value: Any, *, default: str = "") -> str:
    """Format one birthday into localized short-date text."""
    parsed = parse_profile_birthday(value)
    if parsed is None:
        return default
    return tr("time.short_date", year=parsed.year, month=parsed.month, day=parsed.day)


def qdate_from_profile_birthday(value: Any, fallback: QDate) -> QDate:
    """Convert a stored birthday into a QDate for date-edit widgets."""
    parsed = parse_profile_birthday(value)
    if parsed is None:
        return fallback
    return QDate(parsed.year, parsed.month, parsed.day)
