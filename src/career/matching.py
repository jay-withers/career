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

from .distance import distance_miles, find_known_place, find_place_outside_uk
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


# Words that say how senior a role is, not what it is. Left out of title
# matching, so "Senior DevOps Engineer" matches a wanted "DevOps Engineer"
# (and "Lead Engineer" doesn't match a held "Lead Consultant" on "lead").
_SENIORITY_WORDS = frozenset(
    {
        "senior", "sr", "junior", "jr", "lead", "principal", "staff", "head",
        "chief", "mid", "level", "graduate", "trainee", "intern", "i", "ii",
        "iii", "iv", "of", "and", "the", "&", "-",
    }
)  # fmt: skip


def _title_words(title: str) -> set[str]:
    return tokenize(title) - _SENIORITY_WORDS


def _matching_title(listing_title: str, titles: tuple[str, ...]) -> str | None:
    """The first of `titles` whose every word appears in `listing_title`.

    Every word, not any: "DevOps Engineer" must not match "Database
    Engineer" on "engineer" alone. Word order and extra words in the listing
    don't matter ("Engineer, DevOps", "DevOps Engineer (Azure)").
    """
    listing_words = tokenize(listing_title)
    for title in titles:
        words = _title_words(title)
        if words and words <= listing_words:
            return title
    return None


def score(listing: JobListing, profile: Profile) -> tuple[float, tuple[str, ...]]:
    """A 0-100 relevance score for `listing` against `profile`, with reasons.

    `profile.preferences` (see model.JobPreferences) is consulted first and
    can zero the score outright — a title that isn't one of the roles you
    want, an excluded company, a listing mentioning
    none of `required_keywords`, a non-remote listing when remote-only is
    set, a salary below `min_salary`, or a listing further from
    `home_location` than `max_distance_miles` are all treated as a hard "not
    interested" rather than a signal to weigh against the rest. Salary and
    distance only exclude when they're actually known for that listing —
    most sources don't state a salary, and most locations aren't in
    distance.py's small gazetteer, and "can't tell" must not read the same
    as "too far" or "not enough". A location naming a country or major city
    outside the UK (distance.OUTSIDE_UK) counts as known-too-far.

    The title check is against `desired_titles` when any are set, otherwise
    the titles of roles actually held, and needs *every* word of one of
    them (seniority words aside) in the listing's title — see
    `_matching_title`. Past the exclusions, three signals:

    - The title match itself (a flat 60 points — every listing that gets
      this far has one)
    - What fraction of the profile's skills appear in the listing's title or
      description? (up to 40 points, proportional)
    - Does the listing's location match one of `desired_locations`? (a flat
      10-point bonus, capped so the total never exceeds 100)
    """
    prefs = profile.preferences

    wanted_titles = prefs.desired_titles or profile.all_titles
    matched_title = _matching_title(listing.title, wanted_titles) if wanted_titles else None
    if wanted_titles and matched_title is None:
        return 0.0, ("excluded: title doesn't match a role you want",)

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
        # Only against a UK home — "outside the UK" says nothing about how
        # far a listing is from a home the gazetteer can't place.
        abroad = find_place_outside_uk(listing.location)
        if miles is None and abroad is not None and find_known_place(prefs.home_location):
            return 0.0, (
                f"excluded: {listing.location} is outside the UK, further than the "
                f"{prefs.max_distance_miles:.0f} miles you want",
            )

    reasons: list[str] = []

    title_score = 0.0
    if matched_title is not None:
        title_score = 60.0
        if prefs.desired_titles:
            reasons.append(f"title matches a role you want: '{matched_title}'")
        else:
            reasons.append(f"title matches your role '{matched_title}'")

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
