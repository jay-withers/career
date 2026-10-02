"""The daily job: fetch from every configured source, match against the
profile, regenerate market insights and advancement guidance, save.

Run by `career pipeline` — both the scheduled Container Apps Job
(terraform/main.container-apps-job.tf) and the app's own "refresh now"
button call this same function, so there is exactly one implementation of
what a refresh does.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx

from . import store
from .advancement import generate_guidance
from .insights import generate_insights
from .matching import score_all
from .model import JobListing, JobPreferences, JobsDocument
from .settings import settings
from .sources import REGISTRY

logger = logging.getLogger(__name__)

# A "new" listing no source has returned for this long is taken to have been
# filled or withdrawn. Long enough that one source being down for a few days
# doesn't empty the queue; short enough that the cache doesn't grow forever.
STALE_AFTER = timedelta(days=14)


def _configured_sources() -> list[str]:
    return [name.strip() for name in settings().job_sources.split(",") if name.strip()]


def _prune(listings: Iterable[JobListing], sources: set[str]) -> list[JobListing]:
    """Drop "new" listings from sources no longer configured, or not seen lately.

    Anything the person has already acted on (reviewed/applied/dismissed) is
    kept regardless — that's their own record, not the cache's.
    """
    cutoff = datetime.now(UTC) - STALE_AFTER
    return [
        listing
        for listing in listings
        if listing.status != "new" or (listing.source in sources and listing.fetched_at >= cutoff)
    ]


def _fetch_all(preferences: JobPreferences) -> list:
    configured = _configured_sources()
    listings = []
    with httpx.Client(timeout=30.0) as client:
        for name in configured:
            fetch = REGISTRY.get(name)
            if fetch is None:
                logger.warning("unknown job source %r in JOB_SOURCES; skipping", name)
                continue
            try:
                listings.extend(fetch(client, preferences))
            except httpx.HTTPError as exc:
                # One source being briefly unreachable should not lose the
                # others' listings for the day.
                logger.warning("fetching from %s failed: %s", name, exc)
    return listings


def run_pipeline(*, with_guidance: bool = True) -> JobsDocument:
    """Fetch, match, regenerate insights and (unless told not to) guidance.

    `with_guidance=False` is the Jobs page's "refresh now": the advancement
    guidance is one LLM call that takes longer than everything else put
    together, and a person waiting on new listings doesn't need it redone —
    the daily job and the Insights page's refresh still generate it.
    """
    profile, _ = store.load_profile()
    fetched = _fetch_all(profile.preferences)

    def merge(current: JobsDocument) -> JobsDocument:
        # Upsert on (source, external_id): a listing seen before keeps its
        # status (new/reviewed/dismissed/applied) rather than reverting to
        # "new" every day it's still posted, and keeps when it was first
        # seen, but everything else about it — description, match score —
        # refreshes from the latest fetch.
        by_key = {listing.key: listing for listing in current.listings}
        for listing in fetched:
            existing = by_key.get(listing.key)
            if existing is None:
                listing = replace(listing, first_seen=listing.fetched_at)
            else:
                listing = replace(listing, status=existing.status, first_seen=existing.seen_since)
            by_key[listing.key] = listing

        kept = _prune(by_key.values(), set(_configured_sources()))
        scored = score_all(tuple(kept), profile)
        updated = current.with_listings(scored)
        return updated.with_insights(generate_insights(scored, profile))

    result = store.update_jobs(merge)

    # Outside `merge`, which update_jobs may re-run on an ETag conflict —
    # a slow LLM call there would be repeated with it, and would widen the
    # window for the conflict in the first place.
    if with_guidance:
        guidance = generate_guidance(profile, result.insights)
        if guidance is not None:
            result = store.update_jobs(lambda current: current.with_guidance(guidance))

    logger.info(
        "pipeline complete: %d listing(s) fetched, %d total cached",
        len(fetched),
        len(result.listings),
    )
    return result
