from __future__ import annotations

import httpx
import pytest
import respx

from career.model import JobPreferences
from career.sources import reed


@respx.mock
def test_reed_fetch_returns_empty_without_a_key() -> None:
    with httpx.Client() as client:
        assert reed.fetch(client, JobPreferences()) == []
    assert not respx.calls.called


def _reed_result(job_id: int, title: str = "Platform Engineer") -> dict:
    return {
        "jobId": job_id,
        "jobTitle": title,
        "employerName": "Acme",
        "locationName": "Southampton",
        "jobUrl": f"https://www.reed.co.uk/jobs/{job_id}",
        "jobDescription": "Azure landing zones.",
        "date": "30/09/2026",
        "minimumSalary": 80000.0,
        "maximumSalary": 95000.0,
    }


@respx.mock
def test_reed_fetch_queries_from_preferences(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REED_API_KEY", "key")
    from career import settings as settings_module

    settings_module.optional_secret.cache_clear()

    route = respx.get(reed.URL).mock(
        side_effect=[
            httpx.Response(200, json={"results": [_reed_result(1), _reed_result(2)]}),
            # The second title's search returns job 2 again, plus a new one.
            httpx.Response(200, json={"results": [_reed_result(2), _reed_result(3)]}),
        ]
    )
    preferences = JobPreferences(
        desired_titles=("Platform Engineer", "DevOps Engineer"),
        home_location="Fareham",
        max_distance_miles=50,
        min_salary=85000,
    )

    with httpx.Client() as client:
        listings = reed.fetch(client, preferences)

    assert [listing.external_id for listing in listings] == ["1", "2", "3"]
    assert listings[0].source == "reed"
    assert listings[0].posted_date is not None
    assert listings[0].posted_date.isoformat() == "2026-09-30"
    assert listings[0].salary_max == 95000.0

    first, second = (call.request for call in route.calls)
    assert first.url.params["keywords"] == "Platform Engineer"
    assert second.url.params["keywords"] == "DevOps Engineer"
    assert first.url.params["locationName"] == "Fareham"
    assert first.url.params["distanceFromLocation"] == "50"
    assert first.url.params["minimumSalary"] == "85000"
    # Basic auth, key as the username and an empty password.
    assert first.headers["authorization"] == "Basic a2V5Og=="


@respx.mock
def test_reed_fetch_searches_nationwide_without_a_distance_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REED_API_KEY", "key")
    from career import settings as settings_module

    settings_module.optional_secret.cache_clear()
    route = respx.get(reed.URL).mock(return_value=httpx.Response(200, json={"results": []}))

    with httpx.Client() as client:
        reed.fetch(client, JobPreferences(desired_titles=("DevOps Engineer",)))

    params = route.calls.last.request.url.params
    assert "locationName" not in params
    assert "minimumSalary" not in params


@respx.mock
def test_reed_fetch_does_not_search_without_desired_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REED_API_KEY", "key")
    from career import settings as settings_module

    settings_module.optional_secret.cache_clear()

    with httpx.Client() as client:
        assert reed.fetch(client, JobPreferences()) == []
    assert not respx.calls.called


@respx.mock
def test_reed_describe_returns_the_full_advert_as_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REED_API_KEY", "key")
    from career import settings as settings_module

    settings_module.optional_secret.cache_clear()
    advert = "<p>Azure &amp; Terraform</p><ul><li>AKS</li><li>Redis</li></ul>"
    respx.get(reed.DETAILS_URL.format(job_id=1)).mock(
        return_value=httpx.Response(200, json={"jobDescription": advert})
    )
    listing = reed.listing(
        source="reed", external_id="1", title="", company="", location="", url="",
        description="Azure ...", posted_date=None, raw_payload={},
    )  # fmt: skip

    with httpx.Client() as client:
        assert reed.describe(client, listing) == "Azure & Terraform AKS Redis"
