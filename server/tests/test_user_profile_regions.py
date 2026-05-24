from __future__ import annotations

from app.services.region_catalog import RegionCatalog


def test_region_catalog_maps_exact_legacy_profile_region_labels() -> None:
    catalog = RegionCatalog()

    assert catalog.match_legacy_region_text("中国大陆 北京") == ("CN", "CN-BJ")
    assert catalog.match_legacy_region_text("韩国 釜山") == ("KR", "KR-26")
    assert catalog.match_legacy_region_text("其他") == (None, None)


def test_region_catalog_localizes_subdivision_names_for_supported_locales() -> None:
    catalog = RegionCatalog()

    zh = catalog.regions(locale="zh-CN")
    zh_antigua = next(item for item in zh["countries"] if item["code"] == "AG")
    zh_austria = next(item for item in zh["countries"] if item["code"] == "AT")
    zh_china = next(item for item in zh["countries"] if item["code"] == "CN")
    zh_korea = next(item for item in zh["countries"] if item["code"] == "KR")
    assert next(item for item in zh_antigua["subdivisions"] if item["code"] == "AG-03")["name"] == "圣乔治区"
    assert next(item for item in zh_austria["subdivisions"] if item["code"] == "AT-3")["name"] == "下奥地利州"
    assert next(item for item in zh_china["subdivisions"] if item["code"] == "CN-BJ")["name"] == "北京市"
    assert next(item for item in zh_korea["subdivisions"] if item["code"] == "KR-26")["name"] == "釜山"

    en = catalog.regions(locale="en-US")
    en_china = next(item for item in en["countries"] if item["code"] == "CN")
    assert next(item for item in en_china["subdivisions"] if item["code"] == "CN-BJ")["name"] == "Beijing"

    ko = catalog.regions(locale="ko-KR")
    ko_china = next(item for item in ko["countries"] if item["code"] == "CN")
    ko_korea = next(item for item in ko["countries"] if item["code"] == "KR")
    assert next(item for item in ko_china["subdivisions"] if item["code"] == "CN-BJ")["name"] == "베이징 시"
    assert next(item for item in ko_korea["subdivisions"] if item["code"] == "KR-26")["name"] == "부산광역시"


def test_profile_regions_endpoint_returns_country_and_subdivision_names(client, user_factory, auth_header) -> None:
    auth = user_factory("region_user", nickname="Region User")

    response = client.get(
        "/api/v1/users/profile/regions",
        params={"locale": "zh-CN"},
        headers=auth_header(auth["access_token"]),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    countries = payload["countries"]
    china = next(item for item in countries if item["code"] == "CN")
    assert china["name"]
    assert china["name"] != "CN"
    beijing = next(item for item in china["subdivisions"] if item["code"] == "CN-BJ")
    assert beijing["name"]
    assert beijing["name"] == "北京市"


def test_profile_update_persists_region_codes_and_rejects_cross_country_subdivision(client, user_factory, auth_header) -> None:
    auth = user_factory("region_update", nickname="Region Update")
    headers = auth_header(auth["access_token"])

    invalid = client.put(
        "/api/v1/users/me",
        json={
            "region_country_code": "CN",
            "region_subdivision_code": "US-CA",
        },
        headers=headers,
    )
    assert invalid.status_code == 422

    updated = client.put(
        "/api/v1/users/me",
        json={
            "region_country_code": "CN",
            "region_subdivision_code": "CN-BJ",
        },
        headers=headers,
    )

    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["region_country_code"] == "CN"
    assert data["region_subdivision_code"] == "CN-BJ"
    assert data["region_display"]
    assert data["region"] == data["region_display"]


def test_profile_update_rejects_legacy_region_string_payload(client, user_factory, auth_header) -> None:
    auth = user_factory("legacy_region", nickname="Legacy Region")

    response = client.put(
        "/api/v1/users/me",
        json={"region": "中国大陆 北京"},
        headers=auth_header(auth["access_token"]),
    )

    assert response.status_code == 422
