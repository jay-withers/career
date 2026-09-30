"""Adzuna's job search API.

Free tier, but keyed — unlike remoteok/arbeitnow, this one needs
`ADZUNA-APP-ID`/`ADZUNA-APP-KEY` in Key Vault (or the environment locally).
Missing keys degrade to "this source contributes nothing" rather than
failing the whole pipeline, since the other two sources need no key at all.

Query and country come from settings (`adzuna_what`/`adzuna_country`) rather
than the profile: Adzuna's API is keyword+country scoped, not a free-text
profile match, so this is deliberately a broad net for the matcher (see
matching.py) to rank rather than a precise filter.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from ..settings import optional_secret, settings
from .base import listing

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs"
RESULTS_PER_PAGE = 50


def fetch(client: httpx.Client) -> list:
    app_id = optional_secret("ADZUNA-APP-ID")
    app_key = optional_secret("ADZUNA-APP-KEY")
    if not app_id or not app_key:
        logger.info("ADZUNA-APP-ID/ADZUNA-APP-KEY not configured; skipping Adzuna")
        return []

    cfg = settings()
    url = f"{BASE_URL}/{cfg.adzuna_country}/search/1"
    response = client.get(
        url,
        params={
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": RESULTS_PER_PAGE,
            "what": cfg.adzuna_what,
            "content-type": "application/json",
        },
    )
    response.raise_for_status()
    payload = response.json()

    listings = []
    for result in payload.get("results", []):
        created = result.get("created", "")
        posted = date.fromisoformat(created[:10]) if created else None
        listings.append(
            listing(
                source="adzuna",
                external_id=str(result.get("id", "")),
                title=result.get("title", ""),
                company=(result.get("company") or {}).get("display_name", ""),
                location=(result.get("location") or {}).get("display_name", ""),
                url=result.get("redirect_url", ""),
                description=result.get("description", ""),
                posted_date=posted,
                raw_payload=result,
                salary_min=result.get("salary_min"),
                salary_max=result.get("salary_max"),
            )
        )
    logger.info("adzuna: fetched %d listing(s)", len(listings))
    return listings
