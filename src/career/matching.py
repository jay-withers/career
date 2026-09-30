"""Rule-based relevance scoring: how well a listing fits the stored profile.

Deliberately not an LLM call — this runs over every fetched listing (a few
hundred a day across three sources), and a per-listing model call would be
the slowest and most expensive part of the pipeline for a score that a plain
token overlap gets close enough to for sorting a review queue. See
advancement.py for the one place an LLM call *is* worth it: synthesizing
career guidance is a reasoning task a token count cannot do.

`score()` is deliberately a plain function rather than a class implementing
some `Matcher` interface: there is exactly one implementation, and a seam
worth naming only becomes worth building the day a second one (an
LLM-scoring matcher, say) actually gets written.
"""

from __future__ import annotations

import re

from .distance import distance_miles
from .model import JobListing, Profile

_WORD_RE = re.compile(r"[a-z0-9+#.]+")


def tokenize(text: str) -> set[str]:
    """Lowercased word tokens, e.g. "Python" -> "python", "Node.js" -> "node.js".

    A trailing "." is stripped after matching rather than excluded from the
    character class: the class has to include "." to keep "Node.js" and
    "C++"/"C#"-style names intact, but that same inclusion glues a sentence's
    closing period onto its last word ("Python." as one token) unless it is
    peeled back off afterwards.
    """
    return {token.rstrip(".") for token in _WORD_RE.findall(text.lower())}


def score(listing: JobListing, profile: Profile) -> tuple[float, tuple[str, ...]]:
    """A 0-100 relevance score for `listing` against `profile`, with reasons.

    `profile.preferences` (see model.JobPreferences) is consulted first and
    can zero the score outright — an excluded company, a listing mentioning
    none of `required_keywords`, a non-remote listing when remote-only is
    set, a salary below `min_salary`, or a listing further from
    `home_location` than `max_distance_miles` are all treated as a hard "not
    interested" rather than a signal to weigh against the rest. Salary and
    distance only exclude when they're actually known for that listing —
    most sources don't state a salary, and most locations aren't in
    distance.py's small gazetteer, and "can't tell" must not read the same
    as "too far" or "not enough". Past that, three signals, weighted so a
    title match (the strongest single predictor of relevance) dominates but
    skill overlap and preference still move the needle:

    - Does the listing's title share a word with a title the profile has
      actually held, or one from `desired_titles`? (60 points, all-or-nothing
      on the *strongest* match)
    - What fraction of the profile's skills appear in the listing's title or
      description? (up to 40 points, proportional)
    - Does the listing's location match one of `desired_locations`? (a flat
      10-point bonus, capped so the total never exceeds 100)
    """
    prefs = profile.preferences

    if prefs.excluded_companies and listing.company.lower() in {
        c.lower() for c in prefs.excluded_companies
    }:
        return 0.0, (f"excluded: you asked to skip {listing.company}",)

    listing_text = tokenize(f"{listing.title} {listing.description}")

    if prefs.required_keywords and not any(
        tokenize(keyword) <= listing_text for keyword in prefs.required_keywords
    ):
        return 0.0, (f"excluded: doesn't mention any of {', '.join(prefs.required_keywords)}",)

    if prefs.remote_only and "remote" not in listing.location.lower():
        return 0.0, ("excluded: you're only looking for remote roles",)

    if prefs.min_salary is not None:
        known_salary = listing.salary_max or listing.salary_min
        if known_salary is not None and known_salary < prefs.min_salary:
            return 0.0, (
                f"excluded: salary tops out below your minimum of {prefs.min_salary:,.0f}",
            )

    if prefs.max_distance_miles is not None and "remote" not in listing.location.lower():
        miles = distance_miles(prefs.home_location, listing.location)
        if miles is not None and miles > prefs.max_distance_miles:
            return 0.0, (
                f"excluded: about {miles:.0f} miles from {prefs.home_location}, "
                f"further than the {prefs.max_distance_miles:.0f} you want",
            )

    listing_title_tokens = tokenize(listing.title)

    reasons: list[str] = []

    title_score = 0.0
    for title in profile.all_titles:
        title_tokens = tokenize(title)
        if title_tokens and title_tokens & listing_title_tokens:
            title_score = 60.0
            reasons.append(f"title matches your role '{title}'")
            break
    if title_score == 0.0:
        for title in prefs.desired_titles:
            title_tokens = tokenize(title)
            if title_tokens and title_tokens & listing_title_tokens:
                title_score = 60.0
                reasons.append(f"title matches a role you want: '{title}'")
                break

    matched_skills = [s for s in profile.all_skills if tokenize(s) <= listing_text]
    skill_score = 0.0
    if profile.all_skills:
        skill_score = 40.0 * (len(matched_skills) / len(profile.all_skills))
        if matched_skills:
            shown = ", ".join(sorted(matched_skills)[:5])
            reasons.append(f"matches skills: {shown}")

    location_bonus = 0.0
    if prefs.desired_locations:
        listing_location_tokens = tokenize(listing.location)
        for location in prefs.desired_locations:
            if tokenize(location) & listing_location_tokens:
                location_bonus = 10.0
                reasons.append(f"location matches a place you want: '{location}'")
                break

    total = min(100.0, title_score + skill_score + location_bonus)
    return round(total, 1), tuple(reasons)


def score_all(listings: tuple[JobListing, ...], profile: Profile) -> tuple[JobListing, ...]:
    """Return `listings` with `match_score`/`match_reasons` filled in, unsorted."""
    from dataclasses import replace

    scored = []
    for listing in listings:
        match_score, reasons = score(listing, profile)
        scored.append(replace(listing, match_score=match_score, match_reasons=reasons))
    return tuple(scored)
