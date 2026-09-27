from __future__ import annotations

from datetime import UTC, date, datetime

from career.matching import score, score_all
from career.model import JobListing, Profile, Role


def _listing(title: str, description: str = "") -> JobListing:
    return JobListing(
        source="test",
        external_id="1",
        title=title,
        company="Acme",
        location="",
        url="",
        description=description,
        posted_date=None,
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_score_rewards_title_match() -> None:
    profile = Profile(roles=(Role(company="A", title="Senior Engineer", started=date(2020, 1, 1)),))

    matched, reasons = score(_listing("Senior Engineer"), profile)
    unmatched, _ = score(_listing("Marketing Manager"), profile)

    assert matched > unmatched
    assert any("title matches" in r for r in reasons)


def test_score_rewards_skill_overlap() -> None:
    profile = Profile(
        roles=(
            Role(
                company="A",
                title="Engineer",
                started=date(2020, 1, 1),
                skills=("Python", "Terraform"),
            ),
        )
    )

    with_skills, reasons = score(
        _listing("Some role", description="We use Python and Terraform daily."), profile
    )
    without_skills, _ = score(_listing("Some role", description="We use Java."), profile)

    assert with_skills > without_skills
    assert any("matches skills" in r for r in reasons)


def test_score_handles_empty_profile() -> None:
    matched, reasons = score(_listing("Anything"), Profile())

    assert matched == 0.0
    assert reasons == ()


def test_score_all_preserves_listing_count() -> None:
    profile = Profile()
    listings = (_listing("A"), _listing("B"))

    scored = score_all(listings, profile)

    assert len(scored) == 2
    assert {s.title for s in scored} == {"A", "B"}
