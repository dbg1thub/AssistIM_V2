"""Country and first-level subdivision catalog for profile regions."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from babel import Locale, UnknownLocaleError
import pycountry

from app.core.errors import AppError, ErrorCode


class RegionCatalog:
    """Resolve, validate, and display ISO country/subdivision region codes."""

    DEFAULT_LOCALE = "zh-CN"
    _SUBDIVISION_RESOURCE_PATH = Path(__file__).resolve().parents[1] / "resources" / "region_subdivisions.json"
    _SUBDIVISION_LOCALE_ALIASES = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "zh-hans": "zh-CN",
        "zh-hans-cn": "zh-CN",
        "en": "en-US",
        "en-us": "en-US",
        "ko": "ko-KR",
        "ko-kr": "ko-KR",
    }
    _LEGACY_COUNTRY_ALIASES = {
        "中国大陆": "CN",
        "中国": "CN",
        "中国香港": "HK",
        "香港": "HK",
        "中国澳门": "MO",
        "澳门": "MO",
        "中国台湾": "TW",
        "台湾": "TW",
        "韩国": "KR",
        "美国": "US",
        "日本": "JP",
    }
    _LEGACY_REGION_ALIASES = {
        "中国大陆 北京": ("CN", "CN-BJ"),
        "中国大陆 上海": ("CN", "CN-SH"),
        "中国大陆 天津": ("CN", "CN-TJ"),
        "中国大陆 重庆": ("CN", "CN-CQ"),
        "中国大陆 河北": ("CN", "CN-HE"),
        "中国大陆 山西": ("CN", "CN-SX"),
        "中国大陆 辽宁": ("CN", "CN-LN"),
        "中国大陆 吉林": ("CN", "CN-JL"),
        "中国大陆 黑龙江": ("CN", "CN-HL"),
        "中国大陆 江苏": ("CN", "CN-JS"),
        "中国大陆 浙江": ("CN", "CN-ZJ"),
        "中国大陆 安徽": ("CN", "CN-AH"),
        "中国大陆 福建": ("CN", "CN-FJ"),
        "中国大陆 江西": ("CN", "CN-JX"),
        "中国大陆 山东": ("CN", "CN-SD"),
        "中国大陆 河南": ("CN", "CN-HA"),
        "中国大陆 湖北": ("CN", "CN-HB"),
        "中国大陆 湖南": ("CN", "CN-HN"),
        "中国大陆 广东": ("CN", "CN-GD"),
        "中国大陆 海南": ("CN", "CN-HI"),
        "中国大陆 四川": ("CN", "CN-SC"),
        "中国大陆 贵州": ("CN", "CN-GZ"),
        "中国大陆 云南": ("CN", "CN-YN"),
        "中国大陆 陕西": ("CN", "CN-SN"),
        "中国大陆 甘肃": ("CN", "CN-GS"),
        "中国大陆 青海": ("CN", "CN-QH"),
        "中国大陆 内蒙古": ("CN", "CN-NM"),
        "中国大陆 广西": ("CN", "CN-GX"),
        "中国大陆 西藏": ("CN", "CN-XZ"),
        "中国大陆 宁夏": ("CN", "CN-NX"),
        "中国大陆 新疆": ("CN", "CN-XJ"),
        "韩国 首尔": ("KR", "KR-11"),
        "韩国 釜山": ("KR", "KR-26"),
        "韩国 大邱": ("KR", "KR-27"),
        "韩国 仁川": ("KR", "KR-28"),
        "韩国 光州": ("KR", "KR-29"),
        "韩国 大田": ("KR", "KR-30"),
        "韩国 蔚山": ("KR", "KR-31"),
        "韩国 世宗": ("KR", "KR-50"),
        "韩国 京畿道": ("KR", "KR-41"),
        "韩国 江原道": ("KR", "KR-42"),
        "韩国 忠清北道": ("KR", "KR-43"),
        "韩国 忠清南道": ("KR", "KR-44"),
        "韩国 全罗北道": ("KR", "KR-45"),
        "韩国 全罗南道": ("KR", "KR-46"),
        "韩国 庆尚北道": ("KR", "KR-47"),
        "韩国 庆尚南道": ("KR", "KR-48"),
        "韩国 济州": ("KR", "KR-49"),
    }

    def regions(self, *, locale: str = DEFAULT_LOCALE) -> dict[str, object]:
        normalized_locale = self.normalize_locale(locale)
        locale_obj = self._locale(normalized_locale)
        countries: list[dict[str, object]] = []
        for country in sorted(pycountry.countries, key=lambda item: self._country_display_name(item.alpha_2, locale_obj)):
            country_code = str(country.alpha_2 or "").upper()
            countries.append(
                {
                    "code": country_code,
                    "name": self._country_display_name(country_code, locale_obj),
                    "subdivisions": self._country_subdivisions(country_code, locale_obj),
                }
            )
        return {"locale": normalized_locale, "countries": countries}

    def validate_region_codes(
        self,
        *,
        country_code: object,
        subdivision_code: object,
    ) -> tuple[str | None, str | None]:
        country = self.normalize_country_code(country_code)
        subdivision = self.normalize_subdivision_code(subdivision_code)
        if not country and subdivision:
            raise AppError(ErrorCode.INVALID_REQUEST, "region country code is required", 422)
        if not country:
            return None, None
        if pycountry.countries.get(alpha_2=country) is None:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid region country code", 422)
        if not subdivision:
            return country, None
        item = pycountry.subdivisions.get(code=subdivision)
        if item is None or str(item.country_code or "").upper() != country:
            raise AppError(ErrorCode.INVALID_REQUEST, "invalid region subdivision code", 422)
        return country, subdivision

    def display_region(
        self,
        *,
        country_code: object,
        subdivision_code: object,
        locale: str = DEFAULT_LOCALE,
    ) -> str:
        country, subdivision = self.validate_region_codes(
            country_code=country_code,
            subdivision_code=subdivision_code,
        )
        if not country:
            return ""
        locale_obj = self._locale(self.normalize_locale(locale))
        country_name = self._country_display_name(country, locale_obj)
        if not subdivision:
            return country_name
        subdivision_name = self._subdivision_display_name(subdivision, locale_obj)
        return f"{country_name} {subdivision_name}" if subdivision_name else country_name

    def match_legacy_region_text(self, value: object) -> tuple[str | None, str | None]:
        """Map exact legacy profile region labels to ISO codes for migration only."""
        text = str(value or "").strip()
        if not text:
            return None, None
        if text in self._LEGACY_REGION_ALIASES:
            return self._LEGACY_REGION_ALIASES[text]
        country_text, _, area_text = text.partition(" ")
        country = self._LEGACY_COUNTRY_ALIASES.get(country_text) or self._match_country_name(country_text)
        if not country:
            return None, None
        area = area_text.strip()
        if not area:
            return country, None
        subdivision = self._match_subdivision_name(country, area)
        return (country, subdivision) if subdivision else (None, None)

    @staticmethod
    def normalize_country_code(value: object) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def normalize_subdivision_code(value: object) -> str:
        return str(value or "").strip().upper()

    @classmethod
    def normalize_locale(cls, value: object) -> str:
        text = str(value or cls.DEFAULT_LOCALE).strip() or cls.DEFAULT_LOCALE
        return text.replace("_", "-")

    @staticmethod
    @lru_cache(maxsize=16)
    def _locale(locale: str) -> Locale:
        try:
            return Locale.parse(str(locale or RegionCatalog.DEFAULT_LOCALE).replace("-", "_"))
        except (UnknownLocaleError, ValueError):
            return Locale.parse(RegionCatalog.DEFAULT_LOCALE.replace("-", "_"))

    @staticmethod
    def _country_display_name(country_code: str, locale: Locale) -> str:
        code = str(country_code or "").upper()
        country = pycountry.countries.get(alpha_2=code)
        return str(locale.territories.get(code) or getattr(country, "name", code) or code)

    def _country_subdivisions(self, country_code: str, locale: Locale) -> list[dict[str, str]]:
        items = list(pycountry.subdivisions.get(country_code=country_code) or [])
        return [
            {"code": str(item.code or "").upper(), "name": self._subdivision_display_name(str(item.code or ""), locale)}
            for item in sorted(items, key=lambda subdivision: self._subdivision_display_name(str(subdivision.code or ""), locale))
        ]

    @staticmethod
    def _subdivision_display_name(subdivision_code: str, locale: Locale) -> str:
        code = str(subdivision_code or "").upper()
        item = pycountry.subdivisions.get(code=code)
        key = code.replace("-", "").lower()
        return str(RegionCatalog._localized_subdivision_name(key, locale) or getattr(item, "name", code) or code)

    @classmethod
    def _localized_subdivision_name(cls, subdivision_key: str, locale: Locale) -> str:
        names = cls._subdivision_names_by_locale().get(cls._subdivision_locale_key(locale), {})
        return str(names.get(str(subdivision_key or "").strip().lower()) or "")

    @classmethod
    def _subdivision_locale_key(cls, locale: Locale) -> str:
        candidates = [
            str(locale).replace("_", "-").lower(),
            "-".join(
                part
                for part in (
                    str(getattr(locale, "language", "") or "").lower(),
                    str(getattr(locale, "script", "") or "").lower(),
                    str(getattr(locale, "territory", "") or "").lower(),
                )
                if part
            ),
            str(getattr(locale, "language", "") or "").lower(),
        ]
        for candidate in candidates:
            if candidate in cls._SUBDIVISION_LOCALE_ALIASES:
                return cls._SUBDIVISION_LOCALE_ALIASES[candidate]
        return cls._SUBDIVISION_LOCALE_ALIASES["en"]

    @classmethod
    @lru_cache(maxsize=1)
    def _subdivision_names_by_locale(cls) -> dict[str, dict[str, str]]:
        payload = json.loads(cls._SUBDIVISION_RESOURCE_PATH.read_text(encoding="utf-8"))
        locales = payload.get("locales") if isinstance(payload, dict) else None
        if not isinstance(locales, dict):
            raise ValueError("region subdivision resource must include locales")
        result: dict[str, dict[str, str]] = {}
        for locale, names in locales.items():
            if not isinstance(names, dict):
                continue
            result[str(locale)] = {
                str(code).strip().lower(): str(name).strip()
                for code, name in names.items()
                if str(code).strip() and str(name).strip()
            }
        return result

    def _match_country_name(self, value: str) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        for country in pycountry.countries:
            code = str(country.alpha_2 or "").upper()
            names = {
                str(getattr(country, "name", "") or "").strip(),
                str(getattr(country, "official_name", "") or "").strip(),
                self._country_display_name(code, self._locale(self.DEFAULT_LOCALE)),
            }
            if text in names:
                return code
        return None

    def _match_subdivision_name(self, country_code: str, value: str) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        locale_obj = self._locale(self.DEFAULT_LOCALE)
        for item in pycountry.subdivisions.get(country_code=country_code) or []:
            code = str(item.code or "").upper()
            names = {
                str(getattr(item, "name", "") or "").strip(),
                self._subdivision_display_name(code, locale_obj),
            }
            if text in names:
                return code
        return None
