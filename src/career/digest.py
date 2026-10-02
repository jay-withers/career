"""The weekly email: this week's new matches, sent through Resend.

Run by `career digest` — the Friday-evening Container Apps Job
(terraform/main.container-apps-job-digest.tf). It reads the job cache the
daily pipeline already wrote rather than fetching anything itself, so it
costs one Resend call and nothing else.

**Resend over the plain HTTP API, not an SDK** — one POST with a bearer
token is the whole integration, and httpx is already a dependency.

**Missing configuration skips the send rather than failing**, the same as a
job board without its key: `RESEND-API-KEY` and `DIGEST-TO` (the recipient,
a secret only to keep a personal address out of this public repo) are both
optional secrets. A Resend error, though, fails the job — "the email didn't
go" must show up as a failed run, not as a quiet log line.

**Retries can't send twice.** The request carries an idempotency key naming
the ISO week, so the job's own retry (or a manual re-run the same week)
is answered by Resend with the email it already sent.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import store
from .matching import is_excluded, work_arrangement
from .model import JobListing, JobsDocument, Profile
from .settings import optional_secret, settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
# How far back "new this week" reaches, and how many listings the email
# shows — enough to skim on a phone, not a second Jobs page.
WINDOW = timedelta(days=7)
TOP_N = 10

_TEMPLATES = Environment(
    loader=FileSystemLoader(pathlib.Path(__file__).parent / "templates" / "email"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_TEMPLATES.filters["work_arrangement"] = work_arrangement


@dataclass(frozen=True)
class Digest:
    subject: str
    html: str
    text: str


def build_digest(profile: Profile, jobs: JobsDocument, now: datetime) -> Digest:
    """Render the email from what's cached. Always produces one — a week with
    nothing new still says so, which is also how a silent failure of the
    daily pipeline gets noticed."""
    waiting = [
        listing for listing in jobs.listings if listing.status == "new" and not is_excluded(listing)
    ]
    since = now - WINDOW
    new_this_week = sorted(
        (listing for listing in waiting if listing.seen_since >= since),
        key=lambda listing: listing.match_score,
        reverse=True,
    )
    shown: list[JobListing] = new_this_week[:TOP_N]

    count = len(new_this_week)
    if count == 0:
        subject = "career: no new matches this week"
    elif count == 1:
        subject = f"career: 1 new match this week — {shown[0].title}"
    else:
        subject = f"career: {count} new matches this week"

    context = {
        "shown": shown,
        "new_count": count,
        "waiting_count": len(waiting),
        "insights": jobs.insights,
        "guidance": jobs.guidance,
        "app_url": settings().app_url.rstrip("/"),
        "week_of": since.strftime("%-d %b"),
        "has_title_keywords": bool(profile.preferences.desired_titles),
    }
    return Digest(
        subject=subject,
        html=_TEMPLATES.get_template("digest.html").render(context),
        text=_TEMPLATES.get_template("digest.txt").render(context),
    )


def _idempotency_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"career-weekly-digest-{year}-W{week:02d}"


def send_digest(now: datetime | None = None) -> bool:
    """Build this week's digest and send it. True if Resend accepted it."""
    now = now or datetime.now(UTC)
    api_key = optional_secret("RESEND-API-KEY")
    recipient = optional_secret("DIGEST-TO")
    if not api_key or not recipient:
        logger.warning("RESEND-API-KEY or DIGEST-TO not configured; skipping the weekly digest")
        return False

    profile, _ = store.load_profile()
    jobs, _ = store.load_jobs()
    digest = build_digest(profile, jobs, now)

    response = httpx.post(
        RESEND_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Idempotency-Key": _idempotency_key(now),
        },
        json={
            "from": settings().digest_from,
            "to": [recipient],
            "subject": digest.subject,
            "html": digest.html,
            "text": digest.text,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    logger.info("weekly digest sent: %s (resend id %s)", digest.subject, response.json().get("id"))
    return True
