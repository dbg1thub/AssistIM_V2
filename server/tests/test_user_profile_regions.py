from __future__ import annotations

from app.services.region_catalog import RegionCatalog


def test_region_catalog_maps_exact_legacy_profile_region_labels() -> None:
    catalog = RegionCatalog()

    assert catalog.match_legacy_region_text("中国大陆 北京") == ("CN", "CN-BJ")
    assert catalog.match_legacy_region_text("韩国 釜山") == ("KR", "KR-26")
    assert catalog.match_legacy_region_text("其他") == (None, None)


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
    assert beijing["name"] != "CN-BJ"


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
