"""Application internationalization helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QLocale

from client.core.config import Language, cfg
from client.core.datetime_utils import coerce_local_datetime


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "resources" / "i18n"
SUPPORTED_LANGUAGE_CODES = ("zh-CN", "en-US", "ko-KR")
DEFAULT_LANGUAGE_CODE = "en-US"

_active_language_code = DEFAULT_LANGUAGE_CODE
_translations: dict[str, str] = {}
_fallback_translations: dict[str, str] = {}


def _load_translation_map(language_code: str) -> dict[str, str]:
    """Load one flat translation map from disk."""
    path = RESOURCE_DIR / f"{language_code}.json"
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


def _language_code_for_locale(locale: QLocale) -> str:
    """Map a QLocale to one of the supported language packs."""
    language = locale.language()
    if language == QLocale.Language.Chinese:
        return "zh-CN"
    if language == QLocale.Language.Korean:
        return "ko-KR"
    return "en-US"


def resolve_language_code(language: Language | None = None) -> str:
    """Resolve config language selection to one supported language code."""
    selected = language if language is not None else cfg.get(cfg.language)
    if selected == Language.AUTO:
        return _language_code_for_locale(QLocale.system())

    locale = selected.value if isinstance(selected, Language) else QLocale.system()
    code = locale.name().replace("_", "-")
    if code in SUPPORTED_LANGUAGE_CODES:
        return code
    return _language_code_for_locale(locale)


def locale_for_language_code(language_code: str) -> QLocale:
    """Return the QLocale matching a supported language code."""
    if language_code == "zh-CN":
        return QLocale(QLocale.Language.Chinese, QLocale.Country.China)
    if language_code == "ko-KR":
        return QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea)
    return QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)


def initialize_i18n(language: Language | None = None) -> str:
    """Load translation resources and apply the selected default locale."""
    global _active_language_code, _translations, _fallback_translations

    _active_language_code = resolve_language_code(language)
    _fallback_translations = _load_translation_map(DEFAULT_LANGUAGE_CODE)
    _translations = dict(_fallback_translations)
    _translations.update(_load_translation_map(_active_language_code))

    QLocale.setDefault(locale_for_language_code(_active_language_code))
    return _active_language_code


def current_language_code() -> str:
    """Return the currently loaded application language code."""
    return _active_language_code


def current_locale() -> QLocale:
    """Return the currently active application locale."""
    return locale_for_language_code(_active_language_code)


def tr(key: str, default: str | None = None, **kwargs: Any) -> str:
    """Translate one key using the active language pack."""
    if not _translations:
        initialize_i18n()

    text = _translations.get(key) or default or key
    if not kwargs:
        return text

    try:
        return text.format(**kwargs)
    except Exception:
        return text


def _normalize_datetime(value: Any) -> datetime | None:
    """Normalize datetime-like values into a naive local datetime."""
    return coerce_local_datetime(value)


def weekday_name(weekday_index: int, *, short: bool = False) -> str:
    """Return a localized weekday label."""
    suffix = "short" if short else "long"
    weekday_keys = (
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    )
    if 0 <= weekday_index < len(weekday_keys):
        return tr(f"time.weekday.{weekday_keys[weekday_index]}.{suffix}")
    return ""


def format_chat_timestamp(value: Any) -> str:
    """Format message timestamps for the chat list."""
    moment = _normalize_datetime(value)
    if moment is None:
        return ""

    locale = current_locale()
    time_text = locale.toString(moment.time(), "HH:mm")
    now = datetime.now()
    today = now.date()
    moment_date = moment.date()

    if moment_date == today:
        return time_text
    if moment_date == today.fromordinal(today.toordinal() - 1):
        return tr("time.yesterday_with_time", time=time_text)

    day_delta = (today - moment_date).days
    if 1 < day_delta <= 7:
        return tr(
            "time.weekday_with_time",
            weekday=weekday_name(moment.weekday(), short=False),
            time=time_text,
        )

    if moment.year == now.year:
        return tr(
            "time.same_year_with_time",
            month=moment.month,
            day=moment.day,
            time=time_text,
        )

    return tr(
        "time.full_year_with_time",
        year=moment.year,
        month=moment.month,
        day=moment.day,
        time=time_text,
    )


def format_session_timestamp(value: Any) -> str:
    """Format timestamps for session-list preview rows."""
    moment = _normalize_datetime(value)
    if moment is None:
        return ""

    locale = current_locale()
    time_text = locale.toString(moment.time(), "HH:mm")
    now = datetime.now()
    today = now.date()
    moment_date = moment.date()

    if moment_date == today:
        return time_text
    if moment_date == today.fromordinal(today.toordinal() - 1):
        return tr("time.yesterday_with_time", time=time_text)
    if (today - moment_date).days < 7:
        return weekday_name(moment.weekday(), short=True)

    return tr(
        "time.short_date",
        year=moment.year,
        month=moment.month,
        day=moment.day,
    )


def format_relative_time(value: Any) -> str:
    """Format a timestamp into a localized relative-time label."""
    moment = _normalize_datetime(value)
    if moment is None:
        return tr("time.just_now") if not value else str(value)

    now = datetime.now()
    count = int(max((now - moment).total_seconds(), 0))
    if count < 60:
        return tr("time.just_now")
    if count < 3600:
        minutes = count // 60
        key = "time.minute_ago" if minutes == 1 else "time.minutes_ago"
        return tr(key, count=minutes)
    if count < 86400:
        hours = count // 3600
        key = "time.hour_ago" if hours == 1 else "time.hours_ago"
        return tr(key, count=hours)
    if count < 86400 * 7:
        days = count // 86400
        key = "time.day_ago" if days == 1 else "time.days_ago"
        return tr(key, count=days)

    locale = current_locale()
    return locale.toString(moment, "MM-dd HH:mm")


def format_file_size(size: Any) -> str:
    """Format bytes into a compact human-readable string."""
    try:
        size_value = float(size)
    except (TypeError, ValueError):
        return ""

    units = ("B", "KB", "MB", "GB", "TB")
    unit_index = 0
    while size_value >= 1024 and unit_index < len(units) - 1:
        size_value /= 1024.0
        unit_index += 1

    if unit_index == 0:
        return f"{int(size_value)} {units[unit_index]}"
    return f"{size_value:.1f} {units[unit_index]}"
