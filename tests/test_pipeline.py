from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career import pipeline, store
from career.model import JobListing, JobsDocument


def _listing(
    source: str, external_id: str, *, age_days: int = 0, status: str = "new"
) -> JobListing:
    return JobListing(
        source=source,
        external_id=external_id,
        title="Engineer",
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

    kept = pipeline._prune(listings, {"reed", "remoteok"})

    assert [listing.external_id for listing in kept] == ["fresh", "applied"]


@pytest.fixture
def no_fetch(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    monkeypatch.setattr(pipeline, "_fetch_all", lambda _preferences: [])
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
