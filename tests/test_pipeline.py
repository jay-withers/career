from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from career import pipeline, store
from career.model import JobListing, JobPreferences, JobsDocument


def _listing(
    source: str, external_id: str, *, age_days: int = 0, status: str = "new"
) -> JobListing:
    return JobListing(
        source=source,
        external_id=external_id,
        title=f"Engineer {external_id}",
        company="Acme",
        location="Remote",
        url="",
        description="",
        posted_date=None,
        fetched_at=datetime.now(UTC) - timedelta(days=age_days),
        status=status,
    )


def test_prune_drops_new_listings_from_unconfigured_sources_or_not_seen_lately() -> None:
    listings = [
        _listing("reed", "fresh"),
        _listing("reed", "stale", age_days=30),
        _listing("arbeitnow", "dropped-source"),
        # Acted on: kept whatever its source or age.
        _listing("arbeitnow", "applied", age_days=30, status="applied"),
    ]

    kept = pipeline._prune(listings, {"reed"})

    assert [listing.external_id for listing in kept] == ["fresh", "applied"]


@pytest.fixture
def no_fetch(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    monkeypatch.setattr(pipeline, "_fetch_all", lambda _preferences: [])
    monkeypatch.setattr(pipeline, "DESCRIBERS", {})
    guidance_calls: list[int] = []

    def fake_guidance(*_: object) -> None:
        guidance_calls.append(1)

    monkeypatch.setattr(pipeline, "generate_guidance", fake_guidance)
    return guidance_calls


def test_run_pipeline_prunes_the_stored_cache(no_fetch: list[int]) -> None:
    # Reed is off by default now: its unanswered listings go, the ones the
    # person acted on stay.
    store.save_jobs(
        JobsDocument(
            listings=(
                _listing("google", "1"),
                _listing("reed", "2"),
                _listing("reed", "3", status="applied"),
            )
        )
    )

    result = pipeline.run_pipeline()

    assert [listing.key for listing in result.listings] == [("google", "1"), ("reed", "3")]


def test_run_pipeline_can_skip_guidance(no_fetch: list[int]) -> None:
    pipeline.run_pipeline(with_guidance=False)
    assert no_fetch == []

    pipeline.run_pipeline()
    assert no_fetch == [1]


def test_run_pipeline_refuses_guidance_without_insights(
    monkeypatch: pytest.MonkeyPatch, no_fetch: list[int]
) -> None:
    # merge always sets insights. If a change ever stops it, fail loudly rather
    # than quietly stop generating guidance.
    monkeypatch.setattr(store, "update_jobs", lambda _change: JobsDocument())

    with pytest.raises(RuntimeError, match="no insights"):
        pipeline.run_pipeline()
    assert no_fetch == []


def test_run_pipeline_keeps_when_a_listing_was_first_seen(
    monkeypatch: pytest.MonkeyPatch, no_fetch: list[int]
) -> None:
    first = datetime.now(UTC) - timedelta(days=5)
    store.save_jobs(
        JobsDocument(listings=(replace(_listing("google", "old", age_days=1), first_seen=first),))
    )
    monkeypatch.setattr(
        pipeline,
        "_fetch_all",
        lambda _preferences: [_listing("google", "old"), _listing("google", "new")],
    )

    result = pipeline.run_pipeline(with_guidance=False)

    by_id = {listing.external_id: listing for listing in result.listings}
    assert by_id["old"].first_seen == first
    assert by_id["new"].first_seen == by_id["new"].fetched_at


def test_fill_descriptions_fetches_each_full_advert_once(monkeypatch: pytest.MonkeyPatch) -> None:
    described: list[str] = []

    def describe(_client: object, listing: JobListing) -> str | None:
        described.append(listing.external_id)
        return None if listing.external_id == "no-key" else f"full advert {listing.external_id}"

    monkeypatch.setattr(pipeline, "DESCRIBERS", {"reed": describe})
    known = replace(_listing("reed", "known"), description="cached advert", full_description=True)
    cached = [known]

    filled = pipeline._fill_descriptions(
        [_listing("reed", "known"), _listing("reed", "new"), _listing("reed", "no-key")], cached
    )

    assert described == ["new", "no-key"]
    by_id = {listing.external_id: listing for listing in filled}
    assert (by_id["known"].description, by_id["known"].full_description) == ("cached advert", True)
    assert (by_id["new"].description, by_id["new"].full_description) == ("full advert new", True)
    assert (by_id["no-key"].description, by_id["no-key"].full_description) == ("", False)


def test_prune_drops_new_listings_a_source_that_answered_no_longer_returns() -> None:
    listings = [
        _listing("reed", "still-posted"),
        _listing("reed", "withdrawn", age_days=1),
        _listing("reed", "reviewed", age_days=1, status="reviewed"),
    ]

    kept = pipeline._prune(listings, {"reed"}, [_listing("reed", "still-posted")])
    # A source that returned nothing may just be down: its listings wait out STALE_AFTER.
    kept_without_answer = pipeline._prune(listings, {"reed"}, [])

    assert [listing.external_id for listing in kept] == ["still-posted", "reviewed"]
    assert len(kept_without_answer) == 3


def test_collapse_reposts_keeps_the_latest_copy_of_one_advert() -> None:
    def posted(external_id: str, day: int, status: str = "new") -> JobListing:
        return replace(
            _listing("reed", external_id, status=status),
            title="Senior SRE",
            company="Spectrum",
            location="Southampton",
            salary_min=75000,
            salary_max=85000,
            posted_date=date(2026, 10, day),
        )

    reposts = [posted("1-oct", 1), posted("12-oct", 12), posted("6-oct", 6)]
    other = _listing("reed", "different-advert")

    kept = pipeline._collapse_reposts([*reposts, other])
    # Once any copy's been acted on, a repost of it isn't news.
    kept_after_dismissing = pipeline._collapse_reposts(
        [posted("1-oct", 1, status="dismissed"), posted("12-oct", 12)]
    )

    assert [listing.external_id for listing in kept] == ["12-oct", "different-advert"]
    assert [listing.external_id for listing in kept_after_dismissing] == ["1-oct"]


def test_fill_descriptions_drops_a_listing_whose_advert_404s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def describe(_client: object, listing: JobListing) -> str | None:
        request = httpx.Request("GET", "https://reed.example/jobs")
        code = 404 if listing.external_id == "withdrawn" else 500
        raise httpx.HTTPStatusError("", request=request, response=httpx.Response(code))

    monkeypatch.setattr(pipeline, "DESCRIBERS", {"reed": describe})

    filled = pipeline._fill_descriptions(
        [_listing("reed", "withdrawn"), _listing("reed", "flaky")], []
    )

    # A 500 keeps the snippet for a retry tomorrow; a 404 means it's gone.
    assert [listing.external_id for listing in filled] == ["flaky"]


def test_collapse_reposts_drops_a_job_already_answered_under_another_source() -> None:
    def advert(source: str, external_id: str, location: str, status: str = "new") -> JobListing:
        return replace(
            _listing(source, external_id, status=status),
            title="Senior  DevOps Engineer",
            company="AVASK",
            location=location,
        )

    dismissed_on_reed = advert("reed", "1", "Southampton", status="dismissed")
    # The same job from Google: another id, its location written another way.
    same_on_google = replace(
        advert("google", "g1", "Southampton, UK"), title="senior devops engineer"
    )
    # One board can carry several roles with one title from one agency.
    another_on_reed = advert("reed", "2", "Portsmouth")
    different_job = replace(advert("google", "g2", "Southampton, UK"), title="Platform Engineer")

    kept = pipeline._collapse_reposts(
        [dismissed_on_reed, same_on_google, another_on_reed, different_job]
    )

    assert [listing.key for listing in kept] == [("reed", "1"), ("reed", "2"), ("google", "g2")]


def test_prune_keeps_a_partial_sources_listing_missing_from_one_run() -> None:
    # Google returns a shifting top 20, so one run not returning a listing
    # doesn't mean it's been withdrawn: it waits for STALE_AFTER instead.
    listings = [_listing("google", "still-ranked"), _listing("google", "ranked-lower", age_days=3)]

    kept = pipeline._prune(listings, {"google"}, [_listing("google", "still-ranked")])

    assert [listing.external_id for listing in kept] == ["still-ranked", "ranked-lower"]


def test_an_answer_elsewhere_covers_only_a_recent_named_job() -> None:
    def advert(source: str, external_id: str, company: str, age_days: int = 0) -> JobListing:
        status = "new" if source == "google" else "dismissed"
        return replace(
            _listing(source, external_id, status=status, age_days=age_days),
            title="DevOps Engineer",
            company=company,
        )

    # An agency's "DevOps Engineer" dismissed long ago, and one with no
    # company at all, say nothing about a new role with that title.
    old_answer = advert("reed", "old", company="Hays", age_days=40)
    unnamed_answer = advert("reed", "unnamed", company=" ")
    new_from_hays = advert("google", "g-hays", company="Hays")
    new_unnamed = advert("google", "g-unnamed", company="")

    kept = pipeline._collapse_reposts([old_answer, unnamed_answer, new_from_hays, new_unnamed])

    assert {listing.external_id for listing in kept} == {"old", "unnamed", "g-hays", "g-unnamed"}


def test_fetch_all_keeps_other_sources_when_one_answers_with_garbage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def garbage(_client: object, _preferences: object) -> list[JobListing]:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setenv("JOB_SOURCES", "google,reed")
    from career import settings as settings_module

    settings_module.settings.cache_clear()
    monkeypatch.setattr(
        pipeline,
        "REGISTRY",
        {"google": garbage, "reed": lambda _client, _preferences: [_listing("reed", "1")]},
    )

    assert [listing.key for listing in pipeline._fetch_all(JobPreferences())] == [("reed", "1")]
