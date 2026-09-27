"""Exercises the local-file fallback only — see conftest.fake_secrets, which
keeps PROFILE_CONTAINER_URL/JOBS_CONTAINER_URL empty for every test.
"""

from __future__ import annotations

from datetime import date

from career import store
from career.model import Profile, Role


def test_load_profile_with_no_local_file_yields_empty_document() -> None:
    profile, etag = store.load_profile()

    assert profile == Profile()
    assert etag is None


def test_update_profile_persists_across_loads() -> None:
    role = Role(company="Acme", title="Engineer", started=date(2020, 1, 1))

    store.update_profile(lambda p: p.with_role(role))
    reloaded, _ = store.load_profile()

    assert reloaded.roles == (role,)


def test_update_jobs_persists_across_loads() -> None:
    from datetime import UTC, datetime

    from career.model import JobListing

    listing = JobListing(
        source="remoteok",
        external_id="42",
        title="Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        description="",
        posted_date=None,
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    store.update_jobs(lambda j: j.with_listings((listing,)))
    reloaded, _ = store.load_jobs()

    assert reloaded.listings == (listing,)
