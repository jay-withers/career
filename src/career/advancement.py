"""Career advancement guidance: the one place in this app an LLM call earns
its cost.

Everything else in the pipeline (matching.py, insights.py) is deterministic
because it runs over every listing and a wrong or slow answer just means a
worse sort order. This is different: synthesizing "given this profile and
this market, what's missing and what's next" is a reasoning task over a
handful of aggregated numbers, run once a day, where a token-overlap rule
has nothing useful to say. Same deterministic-engine-plus-LLM-judgment split
this account already uses in jay-withers/market-agent.

Runs once per pipeline invocation and caches its output in the jobs document
(see model.AdvancementGuidance) — never called per page view.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from .model import AdvancementGuidance, MarketInsights, Profile
from .settings import optional_secret

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5"

_PROMPT_TEMPLATE = """\
You are a career advisor. Given a person's career profile and a summary of \
what the current job market shows for their field, produce a short, honest \
gap analysis.

Profile:
- Titles held: {titles}
- Skills: {skills}
- Certifications: {certifications}

Market signal (from {listing_count} recently fetched job listings):
- Most in-demand of their existing skills: {top_skills}
- Most common job titles seen: {top_titles}

Respond with a JSON object with exactly these keys:
- "skill_gaps": a list of up to 5 skills or certifications that recur in the \
  market signal but are missing from the profile
- "suggested_next_roles": a list of up to 3 plausible next job titles, given \
  the profile's trajectory
- "rationale": a short paragraph (2-4 sentences) explaining the reasoning

Respond with the JSON object only, no other text.
"""


def _build_prompt(profile: Profile, insights: MarketInsights) -> str:
    return _PROMPT_TEMPLATE.format(
        titles=", ".join(profile.all_titles) or "none recorded",
        skills=", ".join(profile.all_skills) or "none recorded",
        certifications=", ".join(c.name for c in profile.certifications) or "none recorded",
        listing_count=insights.listing_count,
        top_skills=", ".join(f"{s} ({n})" for s, n in insights.top_skills) or "not enough data yet",
        top_titles=", ".join(f"{t} ({n})" for t, n in insights.top_titles) or "not enough data yet",
    )


def generate_guidance(profile: Profile, insights: MarketInsights) -> AdvancementGuidance | None:
    """Return fresh guidance, or None if no Anthropic API key is configured.

    Absence is not a failure: the pipeline's other outputs (matched
    listings, market insights) are still useful without this, so a missing
    key skips this step rather than failing the whole run — same pattern as
    the optional job-board keys in sources/adzuna.py.
    """
    api_key = optional_secret("ANTHROPIC-API-KEY")
    if not api_key:
        logger.info("ANTHROPIC-API-KEY not configured; skipping advancement guidance")
        return None

    if insights.listing_count == 0:
        logger.info("no job listings yet; skipping advancement guidance until there's data")
        return None

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(profile, insights)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("advancement guidance response was not valid JSON; discarding")
        return None

    return AdvancementGuidance(
        generated_at=datetime.now(UTC),
        skill_gaps=tuple(parsed.get("skill_gaps", [])),
        suggested_next_roles=tuple(parsed.get("suggested_next_roles", [])),
        rationale=parsed.get("rationale", ""),
    )
