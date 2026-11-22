"""Google for Jobs, through SerpApi's `google_jobs` engine.

Google gathers job adverts from Indeed, LinkedIn, Reed, Totaljobs and
employers' own careers sites (anything that publishes JobPosting structured
data — Teamtailor, Greenhouse, Workday...), and merges the copies of one job
into a single result that lists every place to apply. Indeed has no public
search API and blocks fetching its pages, so this is the only way its
listings, and those only on a company's own site, reach the app.

Keyed — `SERPAPI-API-KEY` in Key Vault, or `SERPAPI_API_KEY` locally. Missing
key degrades to "this source contributes nothing", as Reed does.

**Metered.** SerpApi's free plan is 250 searches a month, and each page of
10 results is one search. So before searching, `fetch` asks SerpApi's
Account API (free, not counted) how many searches this month has used, and
spends no more than `settings().google_jobs_monthly_searches` minus that,
nor more than the account has left, nor more than
`google_jobs_searches_per_run`, so the month's first runs can't leave its
last ones (Thursday's, before the digest) with nothing. Searches go round-robin by page: every
desired title's first page, then every title's second, so a budget that
runs short still covers every title. Cached searches (an identical request
within the hour, e.g. a "refresh now" straight after the scheduled run) are
free, so the request is kept deterministic. If the Account API can't be
read, nothing is searched: an unknown budget is treated as an empty one.

The query is the desired title alone; where to look goes in `location`,
which SerpApi wants as one of Google's canonical location names. The home
location is looked up in SerpApi's (free) Locations API, falling back to
the whole UK when it isn't a known UK place or there's no distance limit.
`lrad` is the radius, which Google treats as a hint, so the matcher's
distance check still applies. Salary isn't a search parameter here; the
matcher excludes on it when the advert states one.

Google's description is usually the whole advert (sometimes cut short with
"…"), and there's no per-job endpoint to fetch more from, so listings are
marked full and the pipeline never asks for a better one.

A search returns Google's top 20 for a title, which shifts from run to run,
so a listing missing from one run hasn't been withdrawn: Google is in
`sources.PARTIAL`, and its listings age out after `pipeline.STALE_AFTER`
instead.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from ..model import JobListing, JobPreferences
from ..settings import optional_secret, settings
from .base import listing

logger = logging.getLogger(__name__)

SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"
LOCATIONS_URL = "https://serpapi.com/locations.json"
# Two pages of 10 per title: past the first 20, Google's ranking has mostly
# drifted off the title.
PAGES_PER_TITLE = 2
NATIONWIDE = "United Kingdom"
KM_PER_MILE = 1.609344

_AGO_RE = re.compile(r"(\d+)\+?\s*(hour|day|week|month)s?\s+ago")
_NUMBER = r"(\d[\d,]*(?:\.\d+)?)\s*(k)?"
_SALARY_RE = re.compile(
    r"£\s*" + _NUMBER + r"(?:\s*(?:-|\u2013|\u2014|to)\s*£?\s*" + _NUMBER + r")?", re.IGNORECASE
)
_ANNUAL_RE = re.compile(r"\b(?:a|per)\s+(?:year|annum)\b|\byearly\b|\bp\.?a\.?\b", re.IGNORECASE)


def _posted_date(posted_at: str | None, today: date) -> date | None:
    """ "3 days ago" → a date. Google gives nothing more exact."""
    if not posted_at:
        return None
    text = posted_at.casefold()
    if "just posted" in text or "today" in text:
        return today
    match = _AGO_RE.search(text)
    if match is None:
        return None
    count, unit = int(match.group(1)), match.group(2)
    days = {"hour": 0, "day": count, "week": 7 * count, "month": 30 * count}[unit]
    if unit == "hour" and count >= 24:
        days = count // 24
    return today - timedelta(days=days)


def _amount(number: str, thousands: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * 1000 if thousands else value


def _salary(text: str | None) -> tuple[float | None, float | None]:
    """An annual sterling salary as (min, max), or (None, None).

    A day or hourly rate isn't comparable with `min_salary`, and a figure in
    another currency isn't either, so both read as "not stated" — which the
    matcher never excludes on.
    """
    if not text or not _ANNUAL_RE.search(text):
        return None, None
    match = _SALARY_RE.search(text)
    if match is None:
        return None, None
    low = _amount(match.group(1), match.group(2))
    high = low if match.group(3) is None else _amount(match.group(3), match.group(4))
    # "£70-90K" or "£70K-90" (dashed either way) puts the K on one figure only.
    if low < 1000 <= high:
        low *= 1000
    elif high < 1000 <= low:
        high *= 1000
    # No annual salary is under £1,000: a figure that small is a misread.
    if low < 1000 or high < 1000:
        return None, None
    return low, high


def _apply_url(result: dict[str, Any]) -> str:
    """The first place to apply, or Google's own page for the job."""
    for option in result.get("apply_options") or ():
        if link := option.get("link"):
            return str(link)
    return str(result.get("share_link", ""))


def _location(client: httpx.Client, preferences: JobPreferences) -> str:
    """Google's canonical name for the home location, or the whole UK."""
    if preferences.max_distance_miles is None or not preferences.home_location.strip():
        return NATIONWIDE
    response = client.get(LOCATIONS_URL, params={"q": preferences.home_location, "limit": 10})
    response.raise_for_status()
    for place in response.json():
        if place.get("country_code") == "GB" and place.get("canonical_name"):
            return str(place["canonical_name"])
    logger.info("google: home location isn't a known UK place; searching the whole UK")
    return NATIONWIDE


def _budget(client: httpx.Client, api_key: str) -> int:
    """Searches this run may make: this run's share, or what's left of the
    month's allowance if that's less."""
    response = client.get(ACCOUNT_URL, params={"api_key": api_key})
    response.raise_for_status()
    account = response.json()
    used = int(account.get("this_month_usage") or 0)
    left = int(account.get("total_searches_left") or 0)
    config = settings()
    return max(
        0,
        min(config.google_jobs_searches_per_run, config.google_jobs_monthly_searches - used, left),
    )


def _listing(job_id: str, result: dict[str, Any], today: date) -> JobListing:
    extensions = result.get("detected_extensions") or {}
    low, high = _salary(extensions.get("salary"))
    return replace(
        listing(
            source="google",
            external_id=job_id,
            title=result.get("title", ""),
            company=result.get("company_name", ""),
            location=result.get("location", ""),
            url=_apply_url(result),
            description=result.get("description", ""),
            posted_date=_posted_date(extensions.get("posted_at"), today),
            raw_payload=result,
            salary_min=low,
            salary_max=high,
        ),
        full_description=True,
    )


def fetch(client: httpx.Client, preferences: JobPreferences) -> list[JobListing]:
    api_key = optional_secret("SERPAPI-API-KEY")
    if not api_key:
        logger.info("SERPAPI-API-KEY not configured; skipping Google Jobs")
        return []
    # One search per distinct title, however it's capitalised.
    titles = tuple({title.casefold(): title for title in preferences.desired_titles}.values())
    if not titles:
        logger.info("no desired titles in the job preferences; skipping Google Jobs")
        return []

    budget = _budget(client, api_key)
    if budget == 0:
        logger.warning("google: this month's search allowance is used up; skipping Google Jobs")
        return []

    base_params: dict[str, str | int] = {
        "engine": "google_jobs",
        "location": _location(client, preferences),
        "google_domain": "google.co.uk",
        "gl": "uk",
        "hl": "en",
        "api_key": api_key,
    }
    if preferences.max_distance_miles is not None and base_params["location"] != NATIONWIDE:
        base_params["lrad"] = round(preferences.max_distance_miles * KM_PER_MILE)

    today = datetime.now(UTC).date()
    by_id: dict[str, JobListing] = {}
    # A title's next page, or None once it has no more (or has had its pages).
    next_tokens: dict[str, str | None] = dict.fromkeys(titles, "")
    searches = 0
    skipped = failed = False
    for _page in range(PAGES_PER_TITLE):
        if failed:
            break
        for title in titles:
            token = next_tokens[title]
            if token is None:
                continue
            if searches >= budget:
                skipped = True
                continue
            params = {**base_params, "q": title}
            if token:
                params["next_page_token"] = token
            searches += 1
            try:
                response = client.get(SEARCH_URL, params=params)
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                # Keep what the earlier searches found: a rate limit or an
                # outage would fail every later search too, so stop here.
                logger.warning("google: a search failed, keeping what was found: %s", exc)
                failed = True
                break
            # "Google hasn't returned any results for this query." comes back
            # as a 200 with an `error` and no results; it isn't charged.
            if "error" in body and not body.get("jobs_results"):
                logger.info("google: no results for a title search: %s", body["error"])
            for result in body.get("jobs_results") or ():
                job_id = str(result.get("job_id", ""))
                if job_id and job_id not in by_id:
                    by_id[job_id] = _listing(job_id, result, today)
            next_tokens[title] = (body.get("serpapi_pagination") or {}).get("next_page_token")
    if skipped:
        logger.warning("google: stopped at this run's search allowance")

    logger.info(
        "google: fetched %d listing(s) in %d search(es) across %d title(s)",
        len(by_id),
        searches,
        len(titles),
    )
    return list(by_id.values())
