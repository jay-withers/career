"""Career advancement guidance: the one place in this app an LLM call earns
its cost.

Everything else in the pipeline (matching.py, insights.py) is deterministic
because it runs over every listing and a wrong or slow answer just means a
worse sort order. This is different: synthesizing "given this profile and
this market, what's missing and what's next" is a reasoning task over a
handful of aggregated numbers, run once a day, where a token-overlap rule
has nothing useful to say. Same deterministic-engine-plus-LLM-judgment split
this account already uses in jay-withers/market-agent.

DeepSeek, not a bigger model — same choice jay-withers/gym-log makes for its
own weekly insight (see that repo's src/gymlog/insights.py), and for the
same reason: this is a once-a-day summary over a handful of numbers, not a
task that needs a frontier model. Its API is OpenAI-compatible, so a plain
`urllib.request` call is enough, same as gym-log's `_complete` — no extra
HTTP client dependency for one call a day.

Runs once per pipeline invocation and caches its output in the jobs document
(see model.AdvancementGuidance) — never called per page view.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import UTC, datetime

from .model import AdvancementGuidance, MarketInsights, Profile
from .settings import optional_secret

logger = logging.getLogger(__name__)

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "You are a career advisor. Given a person's career profile and a summary "
    "of what the current job market shows for their field, produce a short, "
    "honest gap analysis. Respond with a JSON object with exactly these "
    'keys: "skill_gaps" (a list of up to 5 skills or certifications that '
    "recur in the market signal but are missing from the profile), "
    '"suggested_next_roles" (a list of up to 3 plausible next job titles, '
    'given the profile\'s trajectory), and "rationale" (a short paragraph, '
    "2-4 sentences, explaining the reasoning). Respond with the JSON object "
    "only, no other text."
)

_PROMPT_TEMPLATE = """\
Profile:
- Titles held: {titles}
- Skills: {skills}
- Certifications: {certifications}

Market signal (from {listing_count} recently fetched job listings):
- Most in-demand of their existing skills: {top_skills}
- Most common job titles seen: {top_titles}
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


def _complete(prompt: str, api_key: str) -> str:
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        DEEPSEEK_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["choices"][0]["message"]["content"]).strip()


def generate_guidance(profile: Profile, insights: MarketInsights) -> AdvancementGuidance | None:
    """Return fresh guidance, or None if no DeepSeek API key is configured.

    Absence is not a failure: the pipeline's other outputs (matched
    listings, market insights) are still useful without this, so a missing
    key skips this step rather than failing the whole run — same pattern as
    the optional job-board keys in sources/adzuna.py.
    """
    api_key = optional_secret("DEEPSEEK-API-KEY")
    if not api_key:
        logger.info("DEEPSEEK-API-KEY not configured; skipping advancement guidance")
        return None

    if insights.listing_count == 0:
        logger.info("no job listings yet; skipping advancement guidance until there's data")
        return None

    prompt = _build_prompt(profile, insights)
    text = _complete(prompt, api_key)

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
