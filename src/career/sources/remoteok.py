"""RemoteOK's public job listing feed. No key, no auth, a flat JSON array.

The first element of the response is always a legal/rate-limit notice, not a
job — RemoteOK's own API documents this rather than it being an
undocumented quirk to work around silently.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .base import listing

logger = logging.getLogger(__name__)

URL = "https://remoteok.com/api"


def fetch(client: httpx.Client) -> list:
    response = client.get(URL, headers={"User-Agent": "career-app (personal job search tool)"})
    response.raise_for_status()
    payload = response.json()

    listings = []
    for entry in payload:
        # The leading legal-notice entry carries no "id".
        if "id" not in entry:
            continue

        posted = None
        raw_date = entry.get("date", "")
        if raw_date:
            try:
                posted = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
            except ValueError:
                posted = None

        listings.append(
            listing(
                source="remoteok",
                external_id=str(entry.get("id", "")),
                title=entry.get("position", ""),
                company=entry.get("company", ""),
                location=entry.get("location", "") or "Remote",
                url=entry.get("url", ""),
                description=entry.get("description", ""),
                posted_date=posted,
                raw_payload=entry,
            )
        )
    logger.info("remoteok: fetched %d listing(s)", len(listings))
    return listings
