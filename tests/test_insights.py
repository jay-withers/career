from __future__ import annotations

from datetime import UTC, date, datetime

from career.insights import generate_insights
from career.model import JobListing, Profile, Role


def _listing(title: str, description: str = "") -> JobListing:
    return JobListing(
        source="test",
        external_id=title,
        title=title,
        company="",
        location="",
        url="",
        description=description,
        posted_date=None,
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_generate_insights_counts_skill_mentions() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1), skills=("Python",)),)
    )
    listings = (
        _listing("Engineer", description="Needs Python."),
        _listing("Engineer", description="Needs Python and Go."),
        _listing("Manager", description="No overlap here."),
    )

    insights = generate_insights(listings, profile)

    assert insights.listing_count == 3
    assert dict(insights.top_skills) == {"Python": 2}


def test_generate_insights_counts_titles() -> None:
    listings = (_listing("Engineer"), _listing("Engineer"), _listing("Manager"))

    insights = generate_insights(listings, Profile())

    assert dict(insights.top_titles) == {"Engineer": 2, "Manager": 1}


def test_generate_insights_handles_no_listings() -> None:
    insights = generate_insights((), Profile())

    assert insights.listing_count == 0
    assert insights.top_skills == ()
    assert insights.top_titles == ()
