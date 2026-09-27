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

    Two signals, weighted so a title match (the strongest single predictor of
    relevance) dominates but skill overlap still moves the needle:

    - Does the listing's title share a word with a title the profile has
      actually held? (60 points, all-or-nothing on the *strongest* title match)
    - What fraction of the profile's skills appear in the listing's title or
      description? (up to 40 points, proportional)
    """
    listing_text = tokenize(f"{listing.title} {listing.description}")
    listing_title_tokens = tokenize(listing.title)

    reasons: list[str] = []

    title_score = 0.0
    for title in profile.all_titles:
        title_tokens = tokenize(title)
        if title_tokens and title_tokens & listing_title_tokens:
            title_score = 60.0
            reasons.append(f"title matches your role '{title}'")
            break

    matched_skills = [s for s in profile.all_skills if tokenize(s) <= listing_text]
    skill_score = 0.0
    if profile.all_skills:
        skill_score = 40.0 * (len(matched_skills) / len(profile.all_skills))
        if matched_skills:
            shown = ", ".join(sorted(matched_skills)[:5])
            reasons.append(f"matches skills: {shown}")

    return round(title_score + skill_score, 1), tuple(reasons)


def score_all(listings: tuple[JobListing, ...], profile: Profile) -> tuple[JobListing, ...]:
    """Return `listings` with `match_score`/`match_reasons` filled in, unsorted."""
    from dataclasses import replace

    scored = []
    for listing in listings:
        match_score, reasons = score(listing, profile)
        scored.append(replace(listing, match_score=match_score, match_reasons=reasons))
    return tuple(scored)
