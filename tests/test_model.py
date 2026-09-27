from __future__ import annotations

from datetime import UTC, date, datetime

from career.model import (
    Certification,
    JobListing,
    JobsDocument,
    Profile,
    Role,
)


def test_profile_round_trips_through_json() -> None:
    profile = Profile(
        roles=(
            Role(
                company="Acme",
                title="Senior Engineer",
                started=date(2020, 1, 1),
                ended=date(2022, 6, 1),
                skills=("Python", "Terraform"),
            ),
        ),
        certifications=(
            Certification(name="AZ-104", issuing_org="Microsoft", issued=date(2021, 3, 1)),
        ),
        extra_skills=("Public speaking",),
    )

    restored = Profile.from_json(profile.to_json())

    assert restored == profile


def test_all_skills_deduplicates_case_insensitively() -> None:
    profile = Profile(
        roles=(
            Role(company="A", title="Engineer", started=date(2020, 1, 1), skills=("Python",)),
            Role(company="B", title="Engineer", started=date(2021, 1, 1), skills=("python", "Go")),
        ),
        extra_skills=("PYTHON", "Rust"),
    )

    assert profile.all_skills == ("Python", "Go", "Rust")


def test_all_titles_deduplicates_case_insensitively() -> None:
    profile = Profile(
        roles=(
            Role(company="A", title="Engineer", started=date(2020, 1, 1)),
            Role(company="B", title="engineer", started=date(2021, 1, 1)),
            Role(company="C", title="Manager", started=date(2022, 1, 1)),
        ),
    )

    assert profile.all_titles == ("Engineer", "Manager")


def test_with_role_appends_without_mutating_original() -> None:
    profile = Profile()
    role = Role(company="Acme", title="Engineer", started=date(2020, 1, 1))

    updated = profile.with_role(role)

    assert profile.roles == ()
    assert updated.roles == (role,)


def test_with_role_at_replaces_only_that_role() -> None:
    a = Role(company="A", title="Engineer", started=date(2020, 1, 1))
    b = Role(company="B", title="Engineer", started=date(2021, 1, 1))
    profile = Profile(roles=(a, b))
    replacement = Role(company="A Corp", title="Senior Engineer", started=date(2020, 1, 1))

    updated = profile.with_role_at(0, replacement)

    assert updated.roles == (replacement, b)
    assert profile.roles == (a, b)


def test_with_certification_at_replaces_only_that_certification() -> None:
    a = Certification(name="AZ-104", issuing_org="Microsoft")
    b = Certification(name="AWS SAA", issuing_org="AWS")
    profile = Profile(certifications=(a, b))
    replacement = Certification(name="AZ-104", issuing_org="Microsoft", issued=date(2021, 3, 1))

    updated = profile.with_certification_at(0, replacement)

    assert updated.certifications == (replacement, b)
    assert profile.certifications == (a, b)


def test_jobs_document_round_trips_through_json() -> None:
    listing = JobListing(
        source="adzuna",
        external_id="123",
        title="Senior Engineer",
        company="Acme",
        location="London",
        url="https://example.com/job/123",
        description="Build things.",
        posted_date=date(2024, 1, 1),
        fetched_at=datetime(2024, 1, 2, tzinfo=UTC),
        match_score=75.5,
        match_reasons=("title matches your role 'Engineer'",),
    )
    document = JobsDocument(listings=(listing,))

    restored = JobsDocument.from_json(document.to_json())

    assert restored == document


def test_with_listing_status_only_changes_the_matching_listing() -> None:
    a = JobListing(
        source="adzuna",
        external_id="1",
        title="A",
        company="",
        location="",
        url="",
        description="",
        posted_date=None,
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    b = JobListing(
        source="adzuna",
        external_id="2",
        title="B",
        company="",
        location="",
        url="",
        description="",
        posted_date=None,
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    document = JobsDocument(listings=(a, b))

    updated = document.with_listing_status(("adzuna", "1"), "applied")

    statuses = {listing.external_id: listing.status for listing in updated.listings}
    assert statuses == {"1": "applied", "2": "new"}
