from __future__ import annotations

import io
import zipfile
from datetime import date

from career.importer import merge_into_profile, parse_export
from career.model import Profile, Role


def _make_export(
    positions: str = "",
    certifications: str = "",
    skills: str = "",
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        # Nested under a date-stamped folder, same as a real LinkedIn export.
        if positions:
            archive.writestr("Basic_LinkedInDataExport_01-01-2024/Positions.csv", positions)
        if certifications:
            archive.writestr(
                "Basic_LinkedInDataExport_01-01-2024/Certifications.csv", certifications
            )
        if skills:
            archive.writestr("Basic_LinkedInDataExport_01-01-2024/Skills.csv", skills)
    return buffer.getvalue()


def test_parse_export_reads_positions() -> None:
    positions = (
        "Company Name,Title,Description,Location,Started On,Finished On\n"
        "Acme,Senior Engineer,Built things,London,Jan 2020,Jun 2022\n"
    )

    roles, certifications, skills = parse_export(_make_export(positions=positions))

    assert len(roles) == 1
    assert roles[0].company == "Acme"
    assert roles[0].title == "Senior Engineer"
    assert roles[0].started == date(2020, 1, 1)
    assert roles[0].ended == date(2022, 6, 1)
    assert certifications == ()
    assert skills == ()


def test_parse_export_treats_blank_finished_on_as_current() -> None:
    positions = (
        "Company Name,Title,Description,Location,Started On,Finished On\n"
        "Acme,Engineer,,,Jan 2023,\n"
    )

    roles, _, _ = parse_export(_make_export(positions=positions))

    assert roles[0].ended is None


def test_parse_export_reads_certifications_and_skills() -> None:
    certifications = (
        "Name,Url,Authority,Started On,Finished On,License Number\n"
        "AZ-104,https://x,Microsoft,Mar 2021,,ABC123\n"
    )
    skills = "Name\nPython\nTerraform\n"

    _, certs, skills_out = parse_export(_make_export(certifications=certifications, skills=skills))

    assert len(certs) == 1
    assert certs[0].name == "AZ-104"
    assert certs[0].issuing_org == "Microsoft"
    assert skills_out == ("Python", "Terraform")


def test_parse_export_tolerates_missing_files() -> None:
    roles, certifications, skills = parse_export(_make_export())

    assert roles == ()
    assert certifications == ()
    assert skills == ()


def test_merge_into_profile_is_idempotent() -> None:
    positions = (
        "Company Name,Title,Description,Location,Started On,Finished On\n"
        "Acme,Engineer,,,Jan 2020,\n"
    )
    roles, certifications, skills = parse_export(_make_export(positions=positions))

    once = merge_into_profile(Profile(), roles, certifications, skills)
    twice = merge_into_profile(once, roles, certifications, skills)

    assert len(twice.roles) == 1


def test_merge_into_profile_preserves_manual_edits() -> None:
    profile = Profile().with_role(
        Role(
            company="Acme",
            title="Engineer",
            started=date(2020, 1, 1),
            description="hand-written description",
        )
    )
    positions = (
        "Company Name,Title,Description,Location,Started On,Finished On\n"
        "Acme,Engineer,,,Jan 2020,\n"
    )
    roles, certifications, skills = parse_export(_make_export(positions=positions))

    merged = merge_into_profile(profile, roles, certifications, skills)

    assert len(merged.roles) == 1
    assert merged.roles[0].description == "hand-written description"
