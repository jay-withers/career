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

# Phrases that say how a role is worked, checked in work_arrangement's order.
_FULLY_REMOTE_RE = re.compile(r"\b(?:fully|100%|entirely|completely)[\s-]+remote\b")
_HYBRID_RE = re.compile(r"\bhybrid\b")
_NOT_REMOTE_RE = re.compile(r"\b(?:not|no|non)[\s-]+(?:a[\s-]+)?remote\b")
_REMOTE_RE = re.compile(r"\bremote\b|\bwork(?:ing)? from home\b|\bwfh\b|\bhome[\s-]based\b")
_ON_SITE_RE = re.compile(r"\bon[\s-]?site\b|\boffice[\s-]based\b|\bin[\s-]office\b")


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


def work_arrangement(listing: JobListing) -> str | None:
    """The listing's work arrangement — "remote", "hybrid" or "onsite" — or
    None when it doesn't say.

    Read from the location, title and description together — Reed's
    location is usually just a town, so "remote"/"hybrid" is mostly in the
    (truncated) description, if anywhere. "Fully remote" wins outright, then
    any mention of hybrid (a role "hybrid, two days on-site" is hybrid, not
    on-site), then an explicit "not remote", then remote, then on-site.
    """
    text = f"{listing.location} {listing.title} {listing.description}".lower()
    if _FULLY_REMOTE_RE.search(text):
        return "remote"
    if _HYBRID_RE.search(text):
        return "hybrid"
    if _NOT_REMOTE_RE.search(text):
        return "onsite"
    if _REMOTE_RE.search(text):
        return "remote"
    if _ON_SITE_RE.search(text):
        return "onsite"
    return None


def score(listing: JobListing, profile: Profile) -> tuple[float, tuple[str, ...]]:
    """A 0-100 relevance score for `listing` against `profile`, with reasons.

    `profile.preferences` (see model.JobPreferences) is consulted first and
    can zero the score outright — a title that isn't one of the roles you
    want, an excluded company, a listing mentioning
    none of `required_keywords`, a listing worked differently from
    `work_arrangement` (see below), a salary below `min_salary`, or a listing further from
    `home_location` than `max_distance_miles` are all treated as a hard "not
    interested" rather than a signal to weigh against the rest. Salary and
    distance only exclude when they're actually known for that listing —
    most sources don't state a salary, and most locations aren't in
    distance.py's small gazetteer, and "can't tell" must not read the same
    as "too far" or "not enough". A location naming a country or major city
    outside the UK (distance.OUTSIDE_UK) counts as known-too-far.

    `work_arrangement` is the exception to "can't tell isn't excluded" in
    one direction only: "remote" needs a listing that says it's remote (as
    the remote-only checkbox it replaced always did), while "hybrid" excludes
    only a listing that says it's on-site — most don't say either way.

    Which jobs are wanted comes from the job preferences alone, never from
    the roles the profile records: the title check is against
    `desired_titles` only, and needs *every* word of one of them (seniority
    words aside) in the listing's title — see `_matching_title`. With no
    desired titles set there's no title check, and no title points. Past
    the exclusions, three signals:

    - The title match itself (a flat 60 points)
    - What fraction of the profile's skills appear in the listing's title or
      description? (up to 40 points, proportional)
    - Does the listing's location match one of `desired_locations`? (a flat
      10-point bonus, capped so the total never exceeds 100)
    """
    prefs = profile.preferences

    matched_title = _matching_title(listing.title, prefs.desired_titles)
    if prefs.desired_titles and matched_title is None:
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

    arrangement = work_arrangement(listing)
    if prefs.work_arrangement == "remote" and arrangement != "remote":
        return 0.0, ("excluded: you're only looking for fully remote roles",)
    if prefs.work_arrangement == "hybrid" and arrangement == "onsite":
        return 0.0, ("excluded: on-site, and you're looking for remote or hybrid roles",)

    if prefs.min_salary is not None:
        known_salary = listing.salary_max or listing.salary_min
        if known_salary is not None and known_salary < prefs.min_salary:
            return 0.0, (
                f"excluded: salary tops out below your minimum of {prefs.min_salary:,.0f}",
            )

    if prefs.max_distance_miles is not None and arrangement != "remote":
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
        reasons.append(f"title matches a role you want: '{matched_title}'")

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


def is_excluded(listing: JobListing) -> bool:
    """Whether `score` excluded this listing outright, by its own convention:
    an exclusion zeroes the score and gives one reason, prefixed "excluded:"."""
    return listing.match_score == 0.0 and any(
        reason.startswith("excluded:") for reason in listing.match_reasons
    )


def score_all(listings: tuple[JobListing, ...], profile: Profile) -> tuple[JobListing, ...]:
    """Return `listings` with `match_score`/`match_reasons` filled in, unsorted."""
    from dataclasses import replace

    scored = []
    for listing in listings:
        match_score, reasons = score(listing, profile)
        scored.append(replace(listing, match_score=match_score, match_reasons=reasons))
    return tuple(scored)
