"""Every page the application serves.

Server-rendered Jinja2. `POST` handlers redirect rather than render, so a
reload after adding a role or updating a job's status does not resubmit it.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import replace
from datetime import date
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import store
from ..matching import breakdown, is_excluded
from ..matching import work_arrangement as listing_work_arrangement
from ..model import WORK_ARRANGEMENTS, Certification, Role
from ..pipeline import run_pipeline
from ..settings import settings
from . import deps

logger = logging.getLogger(__name__)

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.filters["work_arrangement"] = listing_work_arrangement
# Computed per card at render time, against the profile as it is now — see
# _job.html, which flags a card whose stored score has since gone stale.
templates.env.globals["score_breakdown"] = breakdown

public = APIRouter()
router = APIRouter()


class ConflictResponse(Exception):
    """Raised when a write lost its race twice. Handled in main.create_app."""


# --- login ---------------------------------------------------------------


@public.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_form(request: Request) -> Any:
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@public.post("/login", include_in_schema=False)
def login(request: Request, passcode: str = Form(default="")) -> Any:
    if not deps.check_passcode(passcode):
        # No detail about *why*. "Wrong passcode" and "no passcode
        # configured" are the same message to whoever is typing.
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "That is not it."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        deps.COOKIE_NAME,
        deps.issue(),
        max_age=settings().cookie_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


# --- home ------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> Any:
    profile, _ = store.load_profile()
    jobs, _ = store.load_jobs()

    top_matches = sorted(
        (
            listing
            for listing in jobs.listings
            if listing.status == "new" and not is_excluded(listing)
        ),
        key=lambda listing: listing.match_score,
        reverse=True,
    )[:10]

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "profile": profile,
            "top_matches": top_matches,
            "insights": jobs.insights,
            "guidance": jobs.guidance,
        },
    )


# --- profile -----------------------------------------------------------------


@router.get("/profile")
def profile_page() -> Any:
    """No page of its own (the home page already shows the profile's counts) —
    kept as a redirect to the first section so an old `/profile` link works."""
    return RedirectResponse("/profile/roles", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/profile/roles", response_class=HTMLResponse)
def roles_page(request: Request) -> Any:
    profile, _ = store.load_profile()
    # Newest first, same as every other profile listing — but the index each
    # card's edit form posts back to is its position in profile.roles, the
    # storage order, not the display order.
    indexed_roles = list(enumerate(profile.roles))[::-1]
    return templates.TemplateResponse(
        request, "profile_roles.html", {"profile": profile, "indexed_roles": indexed_roles}
    )


@router.get("/profile/certifications", response_class=HTMLResponse)
def certifications_page(request: Request) -> Any:
    profile, _ = store.load_profile()
    indexed_certifications = list(enumerate(profile.certifications))[::-1]
    return templates.TemplateResponse(
        request,
        "profile_certifications.html",
        {"profile": profile, "indexed_certifications": indexed_certifications},
    )


@router.get("/profile/skills", response_class=HTMLResponse)
def skills_page(request: Request) -> Any:
    profile, _ = store.load_profile()
    # Same storage-order index as roles_page, so each role's skills form can
    # post back to the right role.
    indexed_roles = list(enumerate(profile.roles))[::-1]
    return templates.TemplateResponse(
        request, "profile_skills.html", {"profile": profile, "indexed_roles": indexed_roles}
    )


# Skills (and the job preferences' keywords, below) are edited one at a time,
# as tags — add one, or remove one — rather than as a single comma-separated
# field, so an entry can contain a comma and there's no list to retype to
# change one of them. See _tags.html.


def _with_tag(tags: tuple[str, ...], tag: str) -> tuple[str, ...]:
    tag = tag.strip()
    if not tag or tag.lower() in {t.lower() for t in tags}:
        return tags
    return (*tags, tag)


def _without_tag(tags: tuple[str, ...], tag: str) -> tuple[str, ...]:
    return tuple(t for t in tags if t != tag)


def _change_role_skills(index: int, edit: Any) -> Any:
    def change(p: Any) -> Any:
        if not 0 <= index < len(p.roles):
            raise HTTPException(status_code=404, detail="no such role")
        role = p.roles[index]
        return p.with_role_at(index, replace(role, skills=edit(role.skills)))

    store.update_profile(change)
    return RedirectResponse("/profile/skills", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/skills/roles/{index}/add")
def add_role_skill(index: int, tag: str = Form(...)) -> Any:
    return _change_role_skills(index, lambda skills: _with_tag(skills, tag))


@router.post("/profile/skills/roles/{index}/remove")
def remove_role_skill(index: int, tag: str = Form(...)) -> Any:
    return _change_role_skills(index, lambda skills: _without_tag(skills, tag))


@router.post("/profile/skills/extra/add")
def add_extra_skill(tag: str = Form(...)) -> Any:
    store.update_profile(lambda p: p.with_extra_skills(_with_tag(p.extra_skills, tag)))
    return RedirectResponse("/profile/skills", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/skills/extra/remove")
def remove_extra_skill(tag: str = Form(...)) -> Any:
    store.update_profile(lambda p: p.with_extra_skills(_without_tag(p.extra_skills, tag)))
    return RedirectResponse("/profile/skills", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/profile/preferences", response_class=HTMLResponse)
def preferences_page(request: Request) -> Any:
    profile, _ = store.load_profile()
    return templates.TemplateResponse(request, "profile_preferences.html", {"profile": profile})


@router.post("/profile/preferences")
def update_preferences(
    work_arrangement: str = Form(default="any"),
    min_salary: str = Form(default=""),
    home_location: str = Form(default="Fareham"),
    max_distance_miles: str = Form(default=""),
) -> Any:
    # The keyword, location and company lists aren't on this form (they're
    # tags, with their own add/remove routes below), so carry them over.
    def change(p: Any) -> Any:
        return p.with_preferences(
            replace(
                p.preferences,
                work_arrangement=(
                    work_arrangement if work_arrangement in WORK_ARRANGEMENTS else "any"
                ),
                min_salary=float(min_salary) if min_salary.strip() else None,
                home_location=home_location.strip() or "Fareham",
                max_distance_miles=float(max_distance_miles)
                if max_distance_miles.strip()
                else None,
            )
        )

    store.update_profile(change)
    return RedirectResponse("/profile/preferences", status_code=status.HTTP_303_SEE_OTHER)


# The URL names the UI uses for JobPreferences' tag lists, mapped to the
# fields themselves (the keyword two named before they were labelled as
# keywords).
_PREFERENCE_TAG_FIELDS = {
    "title-keywords": "desired_titles",
    "description-keywords": "required_keywords",
    "locations": "desired_locations",
    "excluded-companies": "excluded_companies",
}


def _change_preference_tags(kind: str, edit: Any) -> Any:
    field_name = _PREFERENCE_TAG_FIELDS.get(kind)
    if field_name is None:
        raise HTTPException(status_code=404, detail="no such preference")

    def change(p: Any) -> Any:
        tags = edit(getattr(p.preferences, field_name))
        return p.with_preferences(replace(p.preferences, **{field_name: tags}))

    store.update_profile(change)
    return RedirectResponse("/profile/preferences", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/preferences/{kind}/add")
def add_preference_tag(kind: str, tag: str = Form(...)) -> Any:
    return _change_preference_tags(kind, lambda tags: _with_tag(tags, tag))


@router.post("/profile/preferences/{kind}/remove")
def remove_preference_tag(kind: str, tag: str = Form(...)) -> Any:
    return _change_preference_tags(kind, lambda tags: _without_tag(tags, tag))


@router.post("/profile/roles")
def add_role(
    company: str = Form(...),
    title: str = Form(...),
    started: str = Form(...),
    ended: str = Form(default=""),
    location: str = Form(default=""),
    employment_type: str = Form(default=""),
    description: str = Form(default=""),
) -> Any:
    # A new role starts with no skills; they're added on the skills page.
    role = Role(
        company=company.strip(),
        title=title.strip(),
        started=date.fromisoformat(started),
        ended=date.fromisoformat(ended) if ended else None,
        location=location.strip(),
        employment_type=employment_type.strip(),
        description=description.strip(),
    )
    store.update_profile(lambda p: p.with_role(role))
    return RedirectResponse("/profile/roles", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/roles/{index}")
def update_role(
    index: int,
    company: str = Form(...),
    title: str = Form(...),
    started: str = Form(...),
    ended: str = Form(default=""),
    location: str = Form(default=""),
    employment_type: str = Form(default=""),
    description: str = Form(default=""),
) -> Any:
    def change(p: Any) -> Any:
        if not 0 <= index < len(p.roles):
            raise HTTPException(status_code=404, detail="no such role")
        # Skills aren't on this form (they're edited on the skills page), so
        # carry the role's existing ones over rather than clearing them.
        role = Role(
            company=company.strip(),
            title=title.strip(),
            started=date.fromisoformat(started),
            ended=date.fromisoformat(ended) if ended else None,
            location=location.strip(),
            employment_type=employment_type.strip(),
            description=description.strip(),
            skills=p.roles[index].skills,
        )
        return p.with_role_at(index, role)

    store.update_profile(change)
    return RedirectResponse("/profile/roles", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/certifications")
def add_certification(
    name: str = Form(...),
    issuing_org: str = Form(default=""),
    issued: str = Form(default=""),
    expires: str = Form(default=""),
    credential_id: str = Form(default=""),
    credential_url: str = Form(default=""),
) -> Any:
    cert = Certification(
        name=name.strip(),
        issuing_org=issuing_org.strip(),
        issued=date.fromisoformat(issued) if issued else None,
        expires=date.fromisoformat(expires) if expires else None,
        credential_id=credential_id.strip(),
        credential_url=credential_url.strip(),
    )
    store.update_profile(lambda p: p.with_certification(cert))
    return RedirectResponse("/profile/certifications", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/certifications/{index}")
def update_certification(
    index: int,
    name: str = Form(...),
    issuing_org: str = Form(default=""),
    issued: str = Form(default=""),
    expires: str = Form(default=""),
    credential_id: str = Form(default=""),
    credential_url: str = Form(default=""),
) -> Any:
    cert = Certification(
        name=name.strip(),
        issuing_org=issuing_org.strip(),
        issued=date.fromisoformat(issued) if issued else None,
        expires=date.fromisoformat(expires) if expires else None,
        credential_id=credential_id.strip(),
        credential_url=credential_url.strip(),
    )

    def change(p: Any) -> Any:
        if not 0 <= index < len(p.certifications):
            raise HTTPException(status_code=404, detail="no such certification")
        return p.with_certification_at(index, cert)

    store.update_profile(change)
    return RedirectResponse("/profile/certifications", status_code=status.HTTP_303_SEE_OTHER)


# --- jobs ------------------------------------------------------------------


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, status_filter: str = "new", show_excluded: bool = False) -> Any:
    profile, _ = store.load_profile()
    jobs, _ = store.load_jobs()
    listings = [listing for listing in jobs.listings if listing.status == status_filter]
    # A listing a job preference excluded outright stays in the cache (the
    # preference may change, and it's re-scored every run) but isn't worth
    # reviewing — hide it from the "new" queue, and say how many were hidden,
    # unless show_excluded asks to see them anyway (e.g. to check a
    # preference isn't filtering out more than intended).
    excluded = 0
    if status_filter == "new":
        excluded = sum(1 for listing in listings if is_excluded(listing))
        if not show_excluded:
            listings = [listing for listing in listings if not is_excluded(listing)]
    listings.sort(key=lambda listing: listing.match_score, reverse=True)
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "listings": listings,
            "status_filter": status_filter,
            "excluded": excluded,
            "show_excluded": show_excluded,
            "profile": profile,
        },
    )


@router.post("/jobs/{source}/{external_id}/status")
def update_job_status(source: str, external_id: str, new_status: str = Form(...)) -> Any:
    if new_status not in {"new", "reviewed", "dismissed", "applied"}:
        new_status = "reviewed"
    store.update_jobs(lambda jobs: jobs.with_listing_status((source, external_id), new_status))
    return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/refresh")
def refresh_jobs() -> Any:
    """The manual escape hatch: run the same pipeline the scheduled job runs,
    minus the slow advancement-guidance step (see run_pipeline)."""
    run_pipeline(with_guidance=False)
    return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)


# --- insights ----------------------------------------------------------------


@router.get("/insights", response_class=HTMLResponse)
def insights_page(request: Request) -> Any:
    jobs, _ = store.load_jobs()
    return templates.TemplateResponse(
        request,
        "insights.html",
        {"insights": jobs.insights, "guidance": jobs.guidance},
    )


@router.post("/insights/refresh")
def refresh_insights() -> Any:
    """The same pipeline `/jobs/refresh` runs — only the redirect differs."""
    run_pipeline()
    return RedirectResponse("/insights", status_code=status.HTTP_303_SEE_OTHER)
