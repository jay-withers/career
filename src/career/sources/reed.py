"""Reed.co.uk's job seeker search API.

Keyed (free, from reed.co.uk/developers) — `REED-API-KEY` in Key Vault, or
`REED_API_KEY` locally, sent as the HTTP basic-auth username with an empty
password, which is how Reed's own docs say to authenticate. Missing key
degrades to "this source contributes nothing" rather than failing the
pipeline.

Unlike the other sources, the query comes from the profile's own
`JobPreferences` rather than a fixed setting: Reed filters server-side on
location, distance and salary, so a Fareham/50-mile/£85k search comes back
already inside those limits instead of as a broad net for the matcher to
throw most of away. One request per desired title (and none at all when
no desired titles are set) — Reed has no OR across
keywords —, de-duplicated on Reed's job id. Required keywords are left to the
matcher rather than added to the query, since Reed's search result carries
only a truncated description and the matcher would then exclude a listing
the query had already vouched for.

That truncated description (a few hundred characters, cut mid-sentence) is
too little to match skills against, so `describe` fetches a listing's whole
advert from Reed's per-job endpoint — one request per listing, which the
pipeline makes once per listing rather than on every run (see
pipeline._fill_descriptions).
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime

import httpx

from ..model import JobListing, JobPreferences
from ..settings import optional_secret
from .base import listing

logger = logging.getLogger(__name__)

URL = "https://www.reed.co.uk/api/1.0/search"
DETAILS_URL = "https://www.reed.co.uk/api/1.0/jobs/{job_id}"
# Reed's own maximum per request.
RESULTS_PER_QUERY = 100


def _parse_date(value: str | None) -> date | None:
    # Reed writes dates as dd/mm/yyyy.
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(markup: str) -> str:
    # Tags become spaces rather than nothing, so "<li>Azure</li><li>AKS</li>"
    # doesn't run together into one word.
    return " ".join(html.unescape(_TAG_RE.sub(" ", markup)).split())


def describe(client: httpx.Client, listing: JobListing) -> str | None:
    """The listing's full advert as plain text, or None without a key."""
    api_key = optional_secret("REED-API-KEY")
    if not api_key:
        return None
    response = client.get(DETAILS_URL.format(job_id=listing.external_id), auth=(api_key, ""))
    response.raise_for_status()
    return _plain_text(response.json().get("jobDescription", "")) or None


def fetch(client: httpx.Client, preferences: JobPreferences) -> list[JobListing]:
    api_key = optional_secret("REED-API-KEY")
    if not api_key:
        logger.info("REED-API-KEY not configured; skipping Reed")
        return []

    base_params: dict[str, str | int] = {"resultsToTake": RESULTS_PER_QUERY}
    # Without a distance limit, search the whole country rather than Reed's
    # default 10-mile radius around the home location.
    if preferences.max_distance_miles is not None:
        base_params["locationName"] = preferences.home_location
        base_params["distanceFromLocation"] = int(preferences.max_distance_miles)
    if preferences.min_salary is not None:
        base_params["minimumSalary"] = int(preferences.min_salary)

    # The search comes from the job preferences alone — no desired titles,
    # no search, rather than guessing one from the roles the profile holds.
    queries = preferences.desired_titles
    if not queries:
        logger.info("no desired titles in the job preferences; skipping Reed")
        return []
    by_id: dict[str, JobListing] = {}
    for keywords in queries:
        response = client.get(URL, params={**base_params, "keywords": keywords}, auth=(api_key, ""))
        response.raise_for_status()
        for result in response.json().get("results", []):
            job_id = str(result.get("jobId", ""))
            if not job_id or job_id in by_id:
                continue
            by_id[job_id] = listing(
                source="reed",
                external_id=job_id,
                title=result.get("jobTitle", ""),
                company=result.get("employerName", ""),
                location=result.get("locationName", ""),
                url=result.get("jobUrl", ""),
                description=result.get("jobDescription", ""),
                posted_date=_parse_date(result.get("date")),
                raw_payload=result,
                salary_min=result.get("minimumSalary"),
                salary_max=result.get("maximumSalary"),
            )

    logger.info("reed: fetched %d listing(s) across %d quer(ies)", len(by_id), len(queries))
    return list(by_id.values())
