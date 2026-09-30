from __future__ import annotations

import httpx
import pytest
import respx

from career.model import JobPreferences
from career.sources import reed, remoteok


@respx.mock
def test_remoteok_fetch_skips_the_leading_legal_notice() -> None:
    respx.get(remoteok.URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"legal": "notice"},
                {
                    "id": "1",
                    "position": "Engineer",
                    "company": "Acme",
                    "location": "Remote",
                    "url": "https://example.com/1",
                    "description": "Build things.",
                    "date": "2024-01-01T00:00:00",
                    "salary_min": 60000,
                    "salary_max": 90000,
                },
            ],
        )
    )

    with httpx.Client() as client:
        listings = remoteok.fetch(client, JobPreferences())

    assert len(listings) == 1
    assert listings[0].source == "remoteok"
    assert listings[0].salary_min == 60000
    assert listings[0].salary_max == 90000


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
        reed.fetch(client, JobPreferences())

    params = route.calls.last.request.url.params
    assert "locationName" not in params
    assert "minimumSalary" not in params
    # No desired titles yet: falls back to the configured default search.
    assert params["keywords"] == "platform engineer"
