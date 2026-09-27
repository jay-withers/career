"""Importing a LinkedIn "Get a copy of your data" export.

LinkedIn's export is a zip containing one CSV per data category. This reads
three of them — `Positions.csv`, `Certifications.csv`, `Skills.csv` — and
ignores everything else in the archive (connections, messages, and so on
are none of this app's business and are never even opened).

**The export itself is never retained.** It is read in-memory from the
uploaded/local zip and discarded once parsed; only the derived `Role`/
`Certification`/skill rows are written to the profile document. See
CLAUDE.md's note on why a LinkedIn export must never reach this repository's
git history.

Idempotent by design: importing the same export twice (or a fresher one
covering the same history) does not duplicate roles or certifications,
matched on the fields LinkedIn itself treats as identifying one.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date

from .model import Certification, Profile, Role

logger = logging.getLogger(__name__)

# LinkedIn writes "Jan 2020" for a started/finished month, and an empty
# string for "present" — never a full date, so day 1 is a synthetic
# placeholder rather than anything LinkedIn actually recorded.
_MONTH_FORMAT = "%b %Y"


def _parse_month(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed
    except ValueError:
        pass
    from datetime import datetime

    try:
        parsed_dt = datetime.strptime(value, _MONTH_FORMAT)
    except ValueError:
        logger.warning("could not parse date %r; leaving it unset", value)
        return None
    return date(parsed_dt.year, parsed_dt.month, 1)


def _read_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    """Rows for `name` inside `archive`, or [] if the export doesn't include it.

    Matched by suffix rather than an exact path: LinkedIn nests these under a
    date-stamped top-level folder that varies per export.
    """
    matches = [n for n in archive.namelist() if n.endswith(name)]
    if not matches:
        logger.info("%s not present in this export; skipping", name)
        return []

    with archive.open(matches[0]) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8-sig")
        return list(csv.DictReader(text))


def _roles_from_positions(rows: list[dict[str, str]]) -> tuple[Role, ...]:
    roles = []
    for row in rows:
        started = _parse_month(row.get("Started On", ""))
        if started is None:
            logger.warning("skipping position with no start date: %r", row.get("Title"))
            continue
        roles.append(
            Role(
                company=row.get("Company Name", "").strip(),
                title=row.get("Title", "").strip(),
                started=started,
                ended=_parse_month(row.get("Finished On", "")),
                location=row.get("Location", "").strip(),
                description=row.get("Description", "").strip(),
            )
        )
    return tuple(roles)


def _certifications_from_rows(rows: list[dict[str, str]]) -> tuple[Certification, ...]:
    certs = []
    for row in rows:
        certs.append(
            Certification(
                name=row.get("Name", "").strip(),
                issuing_org=row.get("Authority", "").strip(),
                issued=_parse_month(row.get("Started On", "")),
                expires=_parse_month(row.get("Finished On", "")),
                credential_id=row.get("License Number", "").strip(),
                credential_url=row.get("Url", "").strip(),
            )
        )
    return tuple(certs)


def _skills_from_rows(rows: list[dict[str, str]]) -> tuple[str, ...]:
    return tuple(row.get("Name", "").strip() for row in rows if row.get("Name", "").strip())


def parse_export(
    zip_bytes: bytes,
) -> tuple[tuple[Role, ...], tuple[Certification, ...], tuple[str, ...]]:
    """Parse a LinkedIn export archive into roles, certifications and skills."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        roles = _roles_from_positions(_read_csv(archive, "Positions.csv"))
        certifications = _certifications_from_rows(_read_csv(archive, "Certifications.csv"))
        skills = _skills_from_rows(_read_csv(archive, "Skills.csv"))
    return roles, certifications, skills


def merge_into_profile(
    profile: Profile,
    roles: tuple[Role, ...],
    certifications: tuple[Certification, ...],
    skills: tuple[str, ...],
) -> Profile:
    """Add whatever from a freshly parsed export isn't already in `profile`.

    Matched on the fields LinkedIn itself treats as identifying: (company,
    title, started) for a role, (name, issuing_org) for a certification.
    Manual edits made after a first import — a corrected description, an
    added skill — are untouched, since this only ever adds rows, never
    replaces one that already exists.
    """
    existing_role_keys = {(r.company, r.title, r.started) for r in profile.roles}
    new_roles = tuple(r for r in roles if (r.company, r.title, r.started) not in existing_role_keys)

    existing_cert_keys = {(c.name, c.issuing_org) for c in profile.certifications}
    new_certs = tuple(
        c for c in certifications if (c.name, c.issuing_org) not in existing_cert_keys
    )

    existing_skills = {s.lower() for s in profile.extra_skills}
    new_skills = tuple(s for s in skills if s.lower() not in existing_skills)

    merged = profile
    for role in new_roles:
        merged = merged.with_role(role)
    for cert in new_certs:
        merged = merged.with_certification(cert)
    if new_skills:
        from dataclasses import replace

        merged = replace(merged, extra_skills=(*merged.extra_skills, *new_skills))

    logger.info(
        "merged LinkedIn export: %d new role(s), %d new certification(s), %d new skill(s)",
        len(new_roles),
        len(new_certs),
        len(new_skills),
    )
    return merged
