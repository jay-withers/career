from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from career import settings as settings_module
from career.model import JobPreferences
from career.sources import google

FAREHAM = {"canonical_name": "Fareham,England,United Kingdom", "country_code": "GB"}


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "key")
    settings_module.optional_secret.cache_clear()


def _account(used: int = 0, left: int = 250) -> httpx.Response:
    return httpx.Response(200, json={"this_month_usage": used, "total_searches_left": left})


def _result(job_id: str, title: str = "Senior DevOps Engineer", **extra: object) -> dict:
    return {
        "job_id": job_id,
        "title": title,
        "company_name": "AVASK",
        "location": "Southampton, UK",
        "via": "Indeed",
        "share_link": f"https://www.google.com/search?jobs={job_id}",
        "description": "Azure, AKS, Terraform and GitHub Actions.",
        "detected_extensions": {"posted_at": "3 days ago", "salary": "£70K\u2013£90K a year"},
        "apply_options": [
            {"title": "Indeed", "link": f"https://uk.indeed.com/viewjob?jk={job_id}"}
        ],
        **extra,
    }


def _page(*results: dict, next_page_token: str | None = None) -> httpx.Response:
    body: dict = {"jobs_results": list(results)}
    if next_page_token:
        body["serpapi_pagination"] = {"next_page_token": next_page_token}
    return httpx.Response(200, json=body)


@respx.mock
def test_fetch_returns_empty_without_a_key() -> None:
    with httpx.Client() as client:
        assert google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer",))) == []
    assert not respx.calls.called


@respx.mock
def test_fetch_does_not_search_without_desired_titles(key: None) -> None:
    with httpx.Client() as client:
        assert google.fetch(client, JobPreferences()) == []
    assert not respx.calls.called


@respx.mock
def test_fetch_searches_each_title_near_home_and_builds_listings(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(return_value=_account())
    locations = respx.get(google.LOCATIONS_URL).mock(
        return_value=httpx.Response(
            200, json=[{"canonical_name": "Fareham", "country_code": "US"}, FAREHAM]
        )
    )
    search = respx.get(google.SEARCH_URL).mock(
        side_effect=[
            _page(_result("a"), _result("b"), next_page_token="devops-2"),
            # The second title finds job b again, plus a new one; no more pages.
            _page(_result("b"), _result("c", title="Platform Engineer")),
            _page(_result("d")),
        ]
    )
    preferences = JobPreferences(
        desired_titles=("DevOps Engineer", "Platform Engineer"),
        home_location="Fareham",
        max_distance_miles=50,
    )

    with httpx.Client() as client:
        listings = google.fetch(client, preferences)

    assert [listing.external_id for listing in listings] == ["a", "b", "c", "d"]
    first = listings[0]
    assert first.source == "google"
    assert first.company == "AVASK"
    assert first.url == "https://uk.indeed.com/viewjob?jk=a"
    assert (first.salary_min, first.salary_max) == (70000, 90000)
    assert first.posted_date is not None
    assert first.full_description

    assert locations.calls.last.request.url.params["q"] == "Fareham"
    requests = [call.request.url.params for call in search.calls]
    # Every title's first page before any title's second.
    assert [(params["q"], params.get("next_page_token")) for params in requests] == [
        ("DevOps Engineer", None),
        ("Platform Engineer", None),
        ("DevOps Engineer", "devops-2"),
    ]
    assert requests[0]["engine"] == "google_jobs"
    assert requests[0]["location"] == "Fareham,England,United Kingdom"
    assert requests[0]["lrad"] == "80"
    assert requests[0]["gl"] == "uk"


@respx.mock
def test_fetch_searches_the_whole_uk_without_a_distance_limit(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(return_value=_account())
    locations = respx.get(google.LOCATIONS_URL)
    search = respx.get(google.SEARCH_URL).mock(return_value=_page())

    with httpx.Client() as client:
        google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer",)))

    assert not locations.called
    params = search.calls.last.request.url.params
    assert params["location"] == "United Kingdom"
    assert "lrad" not in params


@respx.mock
def test_fetch_falls_back_to_the_whole_uk_for_an_unknown_home(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(return_value=_account())
    respx.get(google.LOCATIONS_URL).mock(return_value=httpx.Response(200, json=[]))
    search = respx.get(google.SEARCH_URL).mock(return_value=_page())
    preferences = JobPreferences(
        desired_titles=("DevOps Engineer",), home_location="Nowhereton", max_distance_miles=20
    )

    with httpx.Client() as client:
        google.fetch(client, preferences)

    params = search.calls.last.request.url.params
    assert params["location"] == "United Kingdom"
    assert "lrad" not in params


@respx.mock
def test_fetch_spends_no_more_than_this_months_allowance(
    key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_JOBS_MONTHLY_SEARCHES", "100")
    settings_module.settings.cache_clear()
    respx.get(google.ACCOUNT_URL).mock(return_value=_account(used=98))
    search = respx.get(google.SEARCH_URL).mock(
        return_value=_page(_result("a"), next_page_token="more")
    )
    titles = ("DevOps Engineer", "Platform Engineer", "SRE")

    with httpx.Client() as client:
        google.fetch(client, JobPreferences(desired_titles=titles))

    # Two left of 100: the first two titles' first pages, and nothing more.
    assert [call.request.url.params["q"] for call in search.calls] == list(titles[:2])


@respx.mock
def test_fetch_never_exceeds_what_the_account_has_left(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(return_value=_account(used=0, left=0))
    search = respx.get(google.SEARCH_URL)

    with httpx.Client() as client:
        assert google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer",))) == []

    assert not search.called


@respx.mock
def test_fetch_searches_nothing_when_the_allowance_cant_be_read(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(
        return_value=httpx.Response(401, json={"error": "Invalid API key."})
    )
    search = respx.get(google.SEARCH_URL)

    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer",)))

    assert not search.called


@respx.mock
def test_fetch_treats_googles_no_results_error_as_no_listings(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(return_value=_account())
    respx.get(google.SEARCH_URL).mock(
        return_value=httpx.Response(
            200, json={"error": "Google hasn't returned any results for this query."}
        )
    )

    with httpx.Client() as client:
        assert google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer",))) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£70K\u2013£90K a year", (70000, 90000)),
        ("£70\u201390K a year", (70000, 90000)),
        ("£55,000 - £65,000 per annum", (55000, 65000)),
        ("£80K a year", (80000, 80000)),
        ("£70k\u201390 a year", (70000, 90000)),
        ("£70\u201390 a year", (None, None)),
        ("£500\u2013£550 a day", (None, None)),
        ("$120K\u2013$150K a year", (None, None)),
        (None, (None, None)),
    ],
)
def test_salary(text: str | None, expected: tuple[float | None, float | None]) -> None:
    assert google._salary(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3 days ago", date(2026, 11, 19)),
        ("21 hours ago", date(2026, 11, 22)),
        ("30+ days ago", date(2026, 10, 23)),
        ("2 weeks ago", date(2026, 11, 8)),
        ("Just posted", date(2026, 11, 22)),
        ("Full-time", None),
        (None, None),
    ],
)
def test_posted_date(text: str | None, expected: date | None) -> None:
    assert google._posted_date(text, date(2026, 11, 22)) == expected


def test_apply_url_falls_back_to_googles_page() -> None:
    assert (
        google._apply_url({"share_link": "https://google/x", "apply_options": []})
        == "https://google/x"
    )


@respx.mock
def test_fetch_spends_no_more_than_this_runs_share(
    key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_JOBS_SEARCHES_PER_RUN", "3")
    settings_module.settings.cache_clear()
    respx.get(google.ACCOUNT_URL).mock(return_value=_account())
    search = respx.get(google.SEARCH_URL).mock(
        return_value=_page(_result("a"), next_page_token="more")
    )

    with httpx.Client() as client:
        google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer", "SRE")))

    assert [
        (call.request.url.params["q"], call.request.url.params.get("next_page_token"))
        for call in search.calls
    ] == [("DevOps Engineer", None), ("SRE", None), ("DevOps Engineer", "more")]


@respx.mock
def test_fetch_searches_a_repeated_title_once(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(return_value=_account())
    search = respx.get(google.SEARCH_URL).mock(return_value=_page())

    with httpx.Client() as client:
        google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer", "devops engineer")))

    assert search.call_count == 1


@respx.mock
def test_fetch_keeps_what_it_found_when_a_later_search_fails(key: None) -> None:
    respx.get(google.ACCOUNT_URL).mock(return_value=_account())
    search = respx.get(google.SEARCH_URL).mock(
        side_effect=[
            _page(_result("a"), next_page_token="more"),
            httpx.Response(429, json={"error": "rate limited"}),
            _page(_result("never")),
        ]
    )

    with httpx.Client() as client:
        listings = google.fetch(client, JobPreferences(desired_titles=("DevOps Engineer", "SRE")))

    assert [listing.external_id for listing in listings] == ["a"]
    # A rate limit would fail the rest too, so it stops searching.
    assert search.call_count == 2
