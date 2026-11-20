"""integrity.py: the rules each document keeps, one broken document per rule.

They run in the store's updates, the selfcheck and the backup, so a wrong rule
refuses a good edit or rolls back a good release. The seed passing shows they
don't fire on real shapes.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from appkit import integrity as kit

from career import integrity, seed
from career.model import Certification, JobListing, JobPreferences, JobsDocument, Profile, Role

ROLE = Role(company="Acme", title="Engineer", started=date(2020, 1, 1))


def _listing(external_id: str = "1", status: str = "new") -> JobListing:
    return JobListing(
        source="reed",
        external_id=external_id,
        title="Platform Engineer",
        company="Contoso",
        location="Fareham",
        url="https://example.com",
        description="",
        posted_date=None,
        fetched_at=datetime(2026, 11, 1, tzinfo=UTC),
        status=status,
    )


def test_the_seed_keeps_every_rule():
    profile = seed.synthetic_profile()
    assert integrity.check_profile(profile) == []
    assert integrity.check_jobs(seed.synthetic_jobs(profile)) == []


def test_empty_documents_keep_every_rule():
    assert integrity.check_profile(Profile()) == []
    assert integrity.check_jobs(JobsDocument()) == []


def test_a_current_role_and_a_one_day_role_are_fine():
    one_day = replace(ROLE, ended=ROLE.started)
    assert integrity.check_profile(Profile(roles=(ROLE, one_day))) == []


def test_a_role_that_ends_before_it_starts():
    bad = replace(ROLE, ended=date(2019, 12, 31))
    assert integrity.check_profile(Profile(roles=(ROLE, bad))) == [
        "roles[1]: ends before it starts"
    ]


def test_a_certification_that_expires_before_it_was_issued():
    cert = Certification(
        name="AZ-104", issuing_org="Microsoft", issued=date(2024, 5, 1), expires=date(2024, 4, 1)
    )
    assert integrity.check_profile(Profile(certifications=(cert,))) == [
        "certifications[0]: expires before it was issued"
    ]


def test_an_unknown_work_arrangement():
    profile = Profile(preferences=JobPreferences(work_arrangement="sometimes"))
    assert integrity.check_profile(profile) == [
        "preferences.work_arrangement: not one of any/hybrid/remote"
    ]


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
@pytest.mark.parametrize("name", ["min_salary", "max_distance_miles"])
def test_a_preference_number_that_is_negative_or_not_finite(name, value):
    profile = Profile(preferences=JobPreferences(**{name: value}))
    assert integrity.check_profile(profile) == [f"preferences.{name}: not a non-negative number"]


def test_a_listing_stored_twice():
    jobs = JobsDocument(listings=(_listing("7"), _listing("7")))
    assert integrity.check_jobs(jobs) == ["listings (source reed, id 7): stored 2 times"]


def test_a_listing_with_an_unknown_status():
    jobs = JobsDocument(listings=(_listing("7", status="maybe"),))
    assert integrity.check_jobs(jobs) == [
        "listings (source reed, id 7): status is not one of new/reviewed/dismissed/applied"
    ]


def test_a_problem_never_names_a_company_a_title_or_a_salary():
    bad = replace(ROLE, ended=date(2019, 12, 31))
    profile = Profile(roles=(bad,), preferences=JobPreferences(min_salary=-55000.0))
    found = integrity.check_profile(profile)
    assert not any("Acme" in p or "Engineer" in p or "55000" in p for p in found)


# --- the round trip ----------------------------------------------------------------


def _raw(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def test_the_seed_profile_round_trips_with_nothing_dropped():
    raw = seed.synthetic_profile().to_json().encode()
    assert kit.roundtrip(raw, integrity.parse_profile, integrity.dump_profile) == []


def test_a_profile_from_before_work_arrangement_is_a_migration_not_a_loss():
    """`remote_only` is read into work_arrangement; a profile not saved since keeps it."""
    payload = json.loads(Profile().to_json())
    del payload["preferences"]["work_arrangement"]
    payload["preferences"]["remote_only"] = True
    assert kit.roundtrip(_raw(payload), integrity.parse_profile, integrity.dump_profile) == []


def test_an_older_schema_stamp_is_not_a_loss():
    payload = json.loads(Profile().to_json())
    payload["schema_version"] = 0
    assert kit.roundtrip(_raw(payload), integrity.parse_profile, integrity.dump_profile) == []


def test_a_stored_field_this_release_does_not_know_is_reported():
    payload = json.loads(Profile(roles=(ROLE,)).to_json())
    payload["roles"][0]["salary"] = 65000
    found = kit.roundtrip(_raw(payload), integrity.parse_profile, integrity.dump_profile)
    assert found == ["$.roles[0].salary: dropped"]
    assert "65000" not in found[0]


def test_a_migrated_key_missing_on_both_sides_is_ignored():
    payload = json.loads(Profile().to_json())
    del payload["preferences"]
    assert kit.roundtrip(_raw(payload), integrity.parse_profile, integrity.dump_profile) == []


def test_check_parsed_profile_checks_the_profile_half():
    bad = Profile(roles=(replace(ROLE, ended=date(2019, 1, 1)),))
    parsed = integrity.parse_profile(bad.to_json().encode())
    assert integrity.check_parsed_profile(parsed) == ["roles[0]: ends before it starts"]
