"""The shape every job-board adapter returns.

Deliberately not an ABC/Protocol with a `fetch` method to implement against:
each adapter is a plain module-level `fetch(client, preferences) -> list[JobListing]`
function (see `sources/__init__.py`'s registry), which is enough structure
for a few small adapters and needs no class hierarchy to add another.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from ..model import JobListing


def listing(
    *,
    source: str,
    external_id: str,
    title: str,
    company: str,
    location: str,
    url: str,
    description: str,
    posted_date: date | None,
    raw_payload: dict[str, Any],
    salary_min: float | None = None,
    salary_max: float | None = None,
) -> JobListing:
    """Build a `JobListing` with `fetched_at` stamped now, in UTC.

    Every adapter builds its listings through this rather than constructing
    `JobListing` directly, so `fetched_at` and the default match/status
    fields stay consistent across sources. `salary_min`/`salary_max` default
    to None (not stated) — no source's API guarantees a figure.
    """
    return JobListing(
        source=source,
        external_id=external_id,
        title=title,
        company=company,
        location=location,
        url=url,
        description=description,
        posted_date=posted_date,
        fetched_at=datetime.now(UTC),
        raw_payload=raw_payload,
        salary_min=salary_min,
        salary_max=salary_max,
    )
