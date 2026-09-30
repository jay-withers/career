from __future__ import annotations

from datetime import UTC, date, datetime

from career.matching import score, score_all
from career.model import JobListing, JobPreferences, Profile, Role


def _listing(
    title: str,
    description: str = "",
    company: str = "Acme",
    location: str = "",
    salary_min: float | None = None,
    salary_max: float | None = None,
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
        salary_min=salary_min,
        salary_max=salary_max,
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
        _listing("Engineer", description="We use Python and Terraform daily."), profile
    )
    without_skills, _ = score(_listing("Engineer", description="We use Java."), profile)

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


def test_score_needs_every_word_of_a_wanted_title() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Senior Azure Consultant", started=date(2020, 1, 1)),),
        preferences=JobPreferences(desired_titles=("DevOps Engineer",)),
    )

    senior, reasons = score(_listing("Senior DevOps Engineer (m/w/d)"), profile)
    reordered, _ = score(_listing("Engineer - DevOps"), profile)
    database, excluded_reasons = score(_listing("Database Engineer"), profile)
    # Desired titles, once set, replace held ones: "Azure Consultant" no
    # longer counts.
    held_only, _ = score(_listing("Azure Consultant"), profile)

    assert senior > 0.0
    assert any("DevOps Engineer" in r for r in reasons)
    assert reordered > 0.0
    assert database == 0.0
    assert excluded_reasons == ("excluded: title doesn't match a role you want",)
    assert held_only == 0.0


def test_score_ignores_seniority_words_on_both_sides() -> None:
    profile = Profile(roles=(Role(company="A", title="Lead Consultant", started=date(2020, 1, 1)),))

    other_lead, _ = score(_listing("Lead Engineer"), profile)
    consultant, _ = score(_listing("Principal Consultant"), profile)

    assert other_lead == 0.0
    assert consultant > 0.0


def test_score_excludes_a_company_on_the_exclusion_list() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(excluded_companies=("Acme",)),
    )

    matched, reasons = score(_listing("Engineer", company="Acme"), profile)

    assert matched == 0.0
    assert any("excluded" in r for r in reasons)


def test_score_excludes_a_listing_mentioning_none_of_the_required_keywords() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Platform Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(required_keywords=("Azure", "AKS")),
    )

    aws_only, reasons = score(
        _listing("Platform Engineer", description="Build our AWS landing zone with EKS."),
        profile,
    )
    azure, _ = score(
        _listing("Platform Engineer", description="AWS and Azure experience needed."), profile
    )
    aks_in_title, _ = score(_listing("Platform Engineer (AKS)"), profile)

    assert aws_only == 0.0
    assert any("Azure, AKS" in r for r in reasons)
    assert azure > 0.0
    assert aks_in_title > 0.0


def test_score_matches_a_multi_word_required_keyword_on_all_its_words() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(required_keywords=("Microsoft Azure",)),
    )

    matched, _ = score(_listing("Engineer", description="Microsoft Azure, Terraform"), profile)
    partial, _ = score(_listing("Engineer", description="Microsoft 365 admin"), profile)

    assert matched > 0.0
    assert partial == 0.0


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


def test_score_excludes_a_listing_whose_known_salary_is_too_low() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(min_salary=60000),
    )

    too_low, reasons = score(_listing("Engineer", salary_min=40000, salary_max=50000), profile)
    high_enough, _ = score(_listing("Engineer", salary_min=55000, salary_max=70000), profile)
    unstated, _ = score(_listing("Engineer"), profile)

    assert too_low == 0.0
    assert any("salary" in r for r in reasons)
    assert high_enough > 0.0
    # No salary stated at all must not be treated as "below the minimum".
    assert unstated > 0.0


def test_score_excludes_a_listing_beyond_the_distance_preference() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(home_location="Fareham", max_distance_miles=30),
    )

    too_far, reasons = score(_listing("Engineer", location="Glasgow, UK"), profile)
    close_enough, _ = score(_listing("Engineer", location="Southampton, UK"), profile)
    remote, _ = score(_listing("Engineer", location="Remote (UK)"), profile)
    unresolvable, _ = score(_listing("Engineer", location="Somewhere made up"), profile)

    assert too_far == 0.0
    assert any("miles" in r for r in reasons)
    assert close_enough > 0.0
    # Distance is irrelevant to a remote role, and can't be judged for a
    # location this app's gazetteer doesn't know — neither is excluded.
    assert remote > 0.0
    assert unresolvable > 0.0


def test_score_excludes_a_listing_outside_the_uk_under_a_distance_preference() -> None:
    profile = Profile(
        roles=(Role(company="A", title="Engineer", started=date(2020, 1, 1)),),
        preferences=JobPreferences(home_location="Fareham", max_distance_miles=50),
    )

    zurich, reasons = score(_listing("Engineer", location="Zürich"), profile)
    berlin, _ = score(_listing("Engineer", location="Berlin"), profile)
    small_town, _ = score(_listing("Engineer", location="Wuppertal"), profile)
    no_limit, _ = score(
        _listing("Engineer", location="Berlin"),
        Profile(roles=profile.roles, preferences=JobPreferences(home_location="Fareham")),
    )

    assert zurich == 0.0
    assert any("outside the UK" in r for r in reasons)
    assert berlin == 0.0
    # A foreign town too small to be listed is still "can't tell", not excluded.
    assert small_town > 0.0
    # And with no distance limit set, abroad is fine.
    assert no_limit > 0.0


def test_score_all_preserves_listing_count() -> None:
    profile = Profile()
    listings = (_listing("A"), _listing("B"))

    scored = score_all(listings, profile)

    assert len(scored) == 2
    assert {s.title for s in scored} == {"A", "B"}
