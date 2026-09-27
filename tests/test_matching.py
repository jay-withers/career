from __future__ import annotations

from datetime import UTC, date, datetime

from career.matching import score, score_all
from career.model import JobListing, JobPreferences, Profile, Role


def _listing(
    title: str, description: str = "", company: str = "Acme", location: str = ""
) -> JobListing:
    return JobListing(
        source="test",
        external_id="1",
        title=title,
        company=company,
        location=location,
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


def test_score_rewards_desired_title_not_yet_held() -> None:
    # "Product Manager" shares no word with "Engineer", so this only matches
    # through desired_titles, not profile.all_titles.
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(desired_titles=("Product Manager",)),
    )

    matched, reasons = score(_listing("Product Manager"), profile)

    assert matched == 60.0
    assert any("role you want" in r for r in reasons)


def test_score_rewards_desired_location() -> None:
    profile = Profile(preferences=JobPreferences(desired_locations=("Bristol",)))

    matched, reasons = score(_listing("Anything", location="Bristol, UK"), profile)
    unmatched, _ = score(_listing("Anything", location="London, UK"), profile)

    assert matched == 10.0
    assert unmatched == 0.0
    assert any("location matches" in r for r in reasons)


def test_score_excludes_a_company_on_the_exclusion_list() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(excluded_companies=("Acme",)),
    )

    matched, reasons = score(_listing("Engineer", company="Acme"), profile)

    assert matched == 0.0
    assert any("excluded" in r for r in reasons)


def test_score_excludes_non_remote_when_remote_only() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(remote_only=True),
    )

    matched, reasons = score(_listing("Engineer", location="London, UK"), profile)
    still_matched, _ = score(_listing("Engineer", location="Remote (UK)"), profile)

    assert matched == 0.0
    assert any("excluded" in r for r in reasons)
    assert still_matched > 0.0


def test_score_all_preserves_listing_count() -> None:
    profile = Profile()
    listings = (_listing("A"), _listing("B"))

    scored = score_all(listings, profile)

    assert len(scored) == 2
    assert {s.title for s in scored} == {"A", "B"}
