"""Market insights: what the accumulated job-listing corpus says.

Scoped deliberately narrow for v1: rather than open-ended keyword extraction
over free-text descriptions (which needs real NLP to do well), this counts
how often each skill *already in the profile* appears across the fetched
listings, and how often each distinct job title appears. That answers the
question that actually feeds advancement.py — "which of what I already have
is in demand, and what titles keep showing up" — without a new dependency.

Needs enough accumulated listings to say anything useful; a single day's
fetch is a snapshot, not a trend. `listing_count` is carried on the result
so the UI can caveat a small sample honestly rather than presenting day-one
numbers as settled fact.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from .matching import tokenize
from .model import JobListing, MarketInsights, Profile

TOP_N = 15


def generate_insights(listings: tuple[JobListing, ...], profile: Profile) -> MarketInsights:
    skill_counts: Counter[str] = Counter()
    for skill in profile.all_skills:
        skill_tokens = tokenize(skill)
        if not skill_tokens:
            continue
        count = sum(
            1
            for listing in listings
            if skill_tokens <= tokenize(f"{listing.title} {listing.description}")
        )
        if count:
            skill_counts[skill] = count

    title_counts: Counter[str] = Counter(
        listing.title.strip() for listing in listings if listing.title.strip()
    )

    return MarketInsights(
        generated_at=datetime.now(UTC),
        top_skills=tuple(skill_counts.most_common(TOP_N)),
        top_titles=tuple(title_counts.most_common(TOP_N)),
        listing_count=len(listings),
    )
