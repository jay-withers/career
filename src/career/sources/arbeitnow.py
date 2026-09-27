"""Arbeitnow's public job board API. No key, no auth, one page of recent listings."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import httpx

from .base import listing

logger = logging.getLogger(__name__)

URL = "https://www.arbeitnow.com/api/job-board-api"


def fetch(client: httpx.Client) -> list:
    response = client.get(URL)
    response.raise_for_status()
    payload = response.json()

    listings = []
    for entry in payload.get("data", []):
        created = entry.get("created_at")
        posted: date | None = None
        if created:
            posted = datetime.fromtimestamp(created, tz=UTC).date()

        listings.append(
            listing(
                source="arbeitnow",
                external_id=entry.get("slug", ""),
                title=entry.get("title", ""),
                company=entry.get("company_name", ""),
                location=entry.get("location", "") or ("Remote" if entry.get("remote") else ""),
                url=entry.get("url", ""),
                description=entry.get("description", ""),
                posted_date=posted,
                raw_payload=entry,
            )
        )
    logger.info("arbeitnow: fetched %d listing(s)", len(listings))
    return listings
