"""The daily job: fetch from every configured source, match against the
profile, regenerate market insights and advancement guidance, save.

Run by `career pipeline` — both the scheduled Container Apps Job
(terraform/main.container-apps-job.tf) and the app's own "refresh now"
button call this same function, so there is exactly one implementation of
what a refresh does.
"""

from __future__ import annotations

import logging

import httpx

from . import store
from .advancement import generate_guidance
from .insights import generate_insights
from .matching import score_all
from .model import JobsDocument
from .settings import settings
from .sources import REGISTRY

logger = logging.getLogger(__name__)


def _fetch_all() -> list:
    configured = [name.strip() for name in settings().job_sources.split(",") if name.strip()]
    listings = []
    with httpx.Client(timeout=30.0) as client:
        for name in configured:
            fetch = REGISTRY.get(name)
            if fetch is None:
                logger.warning("unknown job source %r in JOB_SOURCES; skipping", name)
                continue
            try:
                listings.extend(fetch(client))
            except httpx.HTTPError as exc:
                # One source being briefly unreachable should not lose the
                # others' listings for the day.
                logger.warning("fetching from %s failed: %s", name, exc)
    return listings


def run_pipeline() -> JobsDocument:
    profile, _ = store.load_profile()
    fetched = _fetch_all()

    def merge(current: JobsDocument) -> JobsDocument:
        # Upsert on (source, external_id): a listing seen before keeps its
        # status (new/reviewed/dismissed/applied) rather than reverting to
        # "new" every day it's still posted, but everything else about it —
        # description, match score — refreshes from the latest fetch.
        by_key = {listing.key: listing for listing in current.listings}
        for listing in fetched:
            existing = by_key.get(listing.key)
            if existing is not None and existing.status != "new":
                from dataclasses import replace

                listing = replace(listing, status=existing.status)
            by_key[listing.key] = listing

        scored = score_all(tuple(by_key.values()), profile)
        updated = current.with_listings(scored)

        insights = generate_insights(scored, profile)
        updated = updated.with_insights(insights)

        guidance = generate_guidance(profile, insights)
        if guidance is not None:
            updated = updated.with_guidance(guidance)

        return updated

    result = store.update_jobs(merge)
    logger.info(
        "pipeline complete: %d listing(s) fetched, %d total cached",
        len(fetched),
        len(result.listings),
    )
    return result
