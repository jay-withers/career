from __future__ import annotations

import pytest

from career import cli, store
from career.seed import synthetic_jobs, synthetic_profile


def test_synthetic_profile_has_a_current_senior_platform_engineer_role() -> None:
    profile = synthetic_profile()

    assert profile.roles
    assert profile.certifications
    current = [role for role in profile.roles if role.ended is None]
    assert len(current) == 1
    assert current[0].title == "Senior Platform Engineer"
    assert "Kubernetes" in profile.all_skills


def test_synthetic_jobs_are_scored_and_carry_insights_and_guidance() -> None:
    profile = synthetic_profile()
    jobs = synthetic_jobs(profile)

    assert jobs.listings
    assert all(listing.source == "synthetic" for listing in jobs.listings)
    # At least the listings whose title/description overlap the profile's
    # current role should score above zero.
    assert any(listing.match_score > 0 for listing in jobs.listings)
    assert jobs.insights is not None
    assert jobs.insights.listing_count == len(jobs.listings)
    assert jobs.guidance is not None
    assert jobs.guidance.rationale


def test_cli_seed_writes_local_files() -> None:
    assert cli.main(["seed"]) == 0

    profile, _ = store.load_profile()
    jobs, _ = store.load_jobs()
    assert profile.roles
    assert jobs.listings


def test_cli_seed_refuses_to_overwrite_existing_profile_without_force() -> None:
    assert cli.main(["seed"]) == 0
    assert cli.main(["seed"]) == 1

    profile, _ = store.load_profile()
    assert profile == synthetic_profile()


def test_cli_seed_force_overwrites() -> None:
    assert cli.main(["seed"]) == 0
    assert cli.main(["seed", "--force"]) == 0


def test_cli_seed_refuses_when_a_container_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROFILE_CONTAINER_URL", "https://example.blob.core.windows.net/profile")
    from career import settings as settings_module

    settings_module.settings.cache_clear()

    assert cli.main(["seed"]) == 1
