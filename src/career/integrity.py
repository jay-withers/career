"""The rules career's two documents must keep, checked wherever they are written.

`Profile.from_json` and `JobsDocument.from_json` forgive missing fields, so a
parse proves little: a role that ends before it starts, a NaN minimum salary
typed into the preferences form, or two copies of one listing all parse.

Through jay-withers/appkit's `appkit.integrity`:

- `store.update_profile`/`update_jobs` refuse a change that adds a problem,
  before anything is sent. One already stored is tolerated, so a document
  never goes read-only.
- `selfcheck` runs appkit's round trip against the live profile after every
  deploy, so a release that would drop a stored value is rolled back before it
  writes. Not the rules: a deploy can't change the data, and one old violation
  would otherwise block every release.
- the nightly backup judges the copied profile's rules and round trip after
  every copy is in R2, which is where a stored violation is reported.

**A problem names where, never what**: a role or certification by its position
(there is no route that deletes one, so positions are stable), a listing by
its source and the board's own id. Never a company, a title or a salary: these
lines reach Log Analytics.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any

from .model import WORK_ARRANGEMENTS, JobsDocument, Profile

__all__ = [
    "LISTING_STATUSES",
    "Parsed",
    "check_jobs",
    "check_parsed_profile",
    "check_profile",
    "dump_profile",
    "parse_profile",
]

# new -> reviewed -> (dismissed | applied), as `JobListing.status` documents.
LISTING_STATUSES = ("new", "reviewed", "dismissed", "applied")

# Stored keys this release reads and migrates rather than keeps, as
# (object path, key). `remote_only` became `work_arrangement`; a profile not
# saved since still carries it, and that is a migration, not data lost.
MIGRATED = ((("preferences",), "remote_only"),)

# What `parse_profile` hands appkit: the profile, and the stored JSON whose
# stamp and migrated keys `dump_profile` carries over.
Parsed = tuple[Profile, dict[str, Any]]


def parse_profile(raw: bytes) -> Parsed:
    """The profile, and the stored JSON for `dump_profile` to carry from."""
    return Profile.from_json(raw.decode("utf-8")), json.loads(raw)


def dump_profile(parsed: Parsed) -> str:
    """The profile as this release writes it, with the stored `schema_version`
    and any `MIGRATED` keys put back, so the round trip judges the data alone.

    A reader that reshapes any other stored field is still reported: add the
    old key to `MIGRATED` with the change that migrates it.
    """
    profile, stored = parsed
    payload = profile.to_dict()
    if "schema_version" in stored:
        payload["schema_version"] = stored["schema_version"]
    for path, key in MIGRATED:
        source: Any = stored
        target: Any = payload
        for part in path:
            source = source.get(part) if isinstance(source, dict) else None
            target = target.get(part) if isinstance(target, dict) else None
        if isinstance(source, dict) and isinstance(target, dict) and key in source:
            target[key] = source[key]
    return json.dumps(payload)


def check_parsed_profile(parsed: Parsed) -> list[str]:
    return check_profile(parsed[0])


def check_profile(profile: Profile) -> list[str]:
    """One line per broken rule; empty when the profile is consistent."""
    problems: list[str] = []
    for i, role in enumerate(profile.roles):
        if role.ended is not None and role.ended < role.started:
            problems.append(f"roles[{i}]: ends before it starts")
    for i, cert in enumerate(profile.certifications):
        if cert.issued is not None and cert.expires is not None and cert.expires < cert.issued:
            problems.append(f"certifications[{i}]: expires before it was issued")

    preferences = profile.preferences
    if preferences.work_arrangement not in WORK_ARRANGEMENTS:
        problems.append("preferences.work_arrangement: not one of " + "/".join(WORK_ARRANGEMENTS))
    for name in ("min_salary", "max_distance_miles"):
        value = getattr(preferences, name)
        if value is not None and not _non_negative(value):
            problems.append(f"preferences.{name}: not a non-negative number")
    return problems


def check_jobs(jobs: JobsDocument) -> list[str]:
    """One line per broken rule in the job cache."""
    problems: list[str] = []
    counts = Counter(listing.key for listing in jobs.listings)
    for (source, external_id), n in sorted(counts.items()):
        if n > 1:
            problems.append(f"listings (source {source}, id {external_id}): stored {n} times")
    for listing in jobs.listings:
        if listing.status not in LISTING_STATUSES:
            problems.append(
                f"listings (source {listing.source}, id {listing.external_id}): "
                "status is not one of " + "/".join(LISTING_STATUSES)
            )
    return problems


def _non_negative(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
