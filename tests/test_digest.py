from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from career import digest, store
from career.model import JobListing, JobPreferences, JobsDocument, Profile

NOW = datetime(2026, 10, 2, 19, 0, tzinfo=UTC)


def _listing(
    external_id: str,
    *,
    score: float = 70.0,
    seen_days_ago: int = 1,
    status: str = "new",
    reasons: tuple[str, ...] = ("title matches",),
) -> JobListing:
    seen = NOW - timedelta(days=seen_days_ago)
    return JobListing(
        source="reed",
        external_id=external_id,
        title=f"Job {external_id}",
        company="Acme",
        location="Southampton (Hybrid)",
        url=f"https://example.com/{external_id}",
        description="",
        posted_date=None,
        fetched_at=NOW,
        match_score=score,
        match_reasons=reasons,
        status=status,
        first_seen=seen,
    )


PROFILE = Profile(preferences=JobPreferences(desired_titles=("Engineer",)))


def test_digest_lists_only_this_weeks_unreviewed_matches_best_first() -> None:
    jobs = JobsDocument(
        listings=(
            _listing("good", score=80),
            _listing("better", score=95),
            _listing("old", seen_days_ago=10),
            _listing("reviewed", status="reviewed"),
            _listing("excluded", score=0.0, reasons=("excluded: on-site",)),
        )
    )

    result = digest.build_digest(PROFILE, jobs, NOW)

    assert result.subject == "career: 2 new matches this week"
    assert result.html.index("Job better") < result.html.index("Job good")
    for absent in ("Job old", "Job reviewed", "Job excluded"):
        assert absent not in result.html
        assert absent not in result.text
    # The older one still counts towards what's waiting for review.
    assert "3 listings in total are waiting for review" in result.html
    assert "Hybrid" in result.text
    assert "https://career.jaywithers.uk/jobs" in result.text


def test_digest_still_goes_out_on_a_quiet_week() -> None:
    result = digest.build_digest(PROFILE, JobsDocument(), NOW)

    assert result.subject == "career: no new matches this week"
    assert "Nothing new matched" in result.html


def test_send_digest_skips_without_resend_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("should not have called Resend")

    monkeypatch.setattr(httpx, "post", fail)

    assert digest.send_digest(NOW) is False


def test_send_digest_posts_to_resend_with_a_weekly_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("DIGEST_TO", "me@example.com")
    store.save_profile(PROFILE)
    store.save_jobs(JobsDocument(listings=(_listing("1"),)))
    calls: list[dict] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(200, json={"id": "abc"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)

    assert digest.send_digest(NOW) is True
    # A retry later the same week reuses the key, so Resend won't send twice.
    digest.send_digest(NOW + timedelta(hours=2))

    (call, retry) = calls
    assert call["url"] == "https://api.resend.com/emails"
    assert call["headers"]["Authorization"] == "Bearer re_test"
    assert call["headers"]["Idempotency-Key"] == "career-weekly-digest-2026-W40"
    assert retry["headers"]["Idempotency-Key"] == call["headers"]["Idempotency-Key"]
    assert call["json"]["to"] == ["me@example.com"]
    assert call["json"]["from"] == "career <digest@career.jaywithers.uk>"
    assert call["json"]["subject"] == "career: 1 new match this week — Job 1"


def test_send_digest_fails_loudly_when_resend_rejects_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("DIGEST_TO", "me@example.com")

    def rejected(url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            403, json={"message": "domain not verified"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", rejected)

    with pytest.raises(httpx.HTTPStatusError):
        digest.send_digest(NOW)


def test_a_cache_saved_before_first_seen_existed_still_loads() -> None:
    listing = replace(_listing("1"), first_seen=None)

    restored = JobListing.from_dict(listing.to_dict())

    assert restored.first_seen is None
    assert restored.seen_since == restored.fetched_at
