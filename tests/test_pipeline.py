from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from career import pipeline, store
from career.model import JobListing, JobsDocument


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
    monkeypatch.setattr(pipeline, "generate_guidance", lambda *_: guidance_calls.append(1) or None)
    return guidance_calls


def test_run_pipeline_prunes_the_stored_cache(no_fetch: list[int]) -> None:
    store.save_jobs(JobsDocument(listings=(_listing("reed", "1"), _listing("adzuna", "2"))))

    result = pipeline.run_pipeline()

    assert [listing.key for listing in result.listings] == [("reed", "1")]


def test_run_pipeline_can_skip_guidance(no_fetch: list[int]) -> None:
    pipeline.run_pipeline(with_guidance=False)
    assert no_fetch == []

    pipeline.run_pipeline()
    assert no_fetch == [1]


def test_run_pipeline_keeps_when_a_listing_was_first_seen(
    monkeypatch: pytest.MonkeyPatch, no_fetch: list[int]
) -> None:
    first = datetime.now(UTC) - timedelta(days=5)
    store.save_jobs(
        JobsDocument(listings=(replace(_listing("reed", "old", age_days=1), first_seen=first),))
    )
    monkeypatch.setattr(
        pipeline,
        "_fetch_all",
        lambda _preferences: [_listing("reed", "old"), _listing("reed", "new")],
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
    def posted(external_id: str, day: int, **kwargs: object) -> JobListing:
        return replace(
            _listing("reed", external_id, **kwargs),
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
