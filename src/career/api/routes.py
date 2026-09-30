"""Every page the application serves.

Server-rendered Jinja2. `POST` handlers redirect rather than render, so a
reload after adding a role or updating a job's status does not resubmit it.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import date
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import store
from ..importer import merge_into_profile, parse_export
from ..model import Certification, JobPreferences, Role
from ..pipeline import run_pipeline
from ..settings import settings
from . import deps

logger = logging.getLogger(__name__)

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

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
        (listing for listing in jobs.listings if listing.status == "new"),
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


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request) -> Any:
    """The profile overview — counts only, linking out to a sub-page per section."""
    profile, _ = store.load_profile()
    return templates.TemplateResponse(request, "profile.html", {"profile": profile})


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
    return templates.TemplateResponse(request, "profile_skills.html", {"profile": profile})


@router.get("/profile/preferences", response_class=HTMLResponse)
def preferences_page(request: Request) -> Any:
    profile, _ = store.load_profile()
    return templates.TemplateResponse(request, "profile_preferences.html", {"profile": profile})


@router.post("/profile/preferences")
def update_preferences(
    desired_titles: str = Form(default=""),
    desired_locations: str = Form(default=""),
    remote_only: str = Form(default=""),
    excluded_companies: str = Form(default=""),
    min_salary: str = Form(default=""),
    home_location: str = Form(default="Fareham"),
    max_distance_miles: str = Form(default=""),
) -> Any:
    preferences = JobPreferences(
        desired_titles=tuple(s.strip() for s in desired_titles.split(",") if s.strip()),
        desired_locations=tuple(s.strip() for s in desired_locations.split(",") if s.strip()),
        remote_only=remote_only == "on",
        excluded_companies=tuple(s.strip() for s in excluded_companies.split(",") if s.strip()),
        min_salary=float(min_salary) if min_salary.strip() else None,
        home_location=home_location.strip() or "Fareham",
        max_distance_miles=float(max_distance_miles) if max_distance_miles.strip() else None,
    )
    store.update_profile(lambda p: p.with_preferences(preferences))
    return RedirectResponse("/profile/preferences", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/roles")
def add_role(
    company: str = Form(...),
    title: str = Form(...),
    started: str = Form(...),
    ended: str = Form(default=""),
    location: str = Form(default=""),
    employment_type: str = Form(default=""),
    description: str = Form(default=""),
    skills: str = Form(default=""),
) -> Any:
    role = Role(
        company=company.strip(),
        title=title.strip(),
        started=date.fromisoformat(started),
        ended=date.fromisoformat(ended) if ended else None,
        location=location.strip(),
        employment_type=employment_type.strip(),
        description=description.strip(),
        skills=tuple(s.strip() for s in skills.split(",") if s.strip()),
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
    skills: str = Form(default=""),
) -> Any:
    role = Role(
        company=company.strip(),
        title=title.strip(),
        started=date.fromisoformat(started),
        ended=date.fromisoformat(ended) if ended else None,
        location=location.strip(),
        employment_type=employment_type.strip(),
        description=description.strip(),
        skills=tuple(s.strip() for s in skills.split(",") if s.strip()),
    )

    def change(p: Any) -> Any:
        if not 0 <= index < len(p.roles):
            raise HTTPException(status_code=404, detail="no such role")
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


# --- LinkedIn import -----------------------------------------------------------


@router.get("/profile/import", response_class=HTMLResponse)
def import_form(request: Request) -> Any:
    return templates.TemplateResponse(request, "import.html", {})


@router.post("/profile/import")
async def import_linkedin(export: UploadFile) -> Any:
    """Parse an uploaded LinkedIn export and merge it into the profile.

    The upload is held only in memory for the length of this request — see
    importer.py's module docstring on why the export itself is never
    written to disk or retained.
    """
    zip_bytes = await export.read()
    roles, certifications, skills = parse_export(zip_bytes)
    store.update_profile(lambda p: merge_into_profile(p, roles, certifications, skills))
    return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)


# --- jobs ------------------------------------------------------------------


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, status_filter: str = "new") -> Any:
    jobs, _ = store.load_jobs()
    listings = [listing for listing in jobs.listings if listing.status == status_filter]
    listings.sort(key=lambda listing: listing.match_score, reverse=True)
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {"listings": listings, "status_filter": status_filter},
    )


@router.post("/jobs/{source}/{external_id}/status")
def update_job_status(source: str, external_id: str, new_status: str = Form(...)) -> Any:
    if new_status not in {"new", "reviewed", "dismissed", "applied"}:
        new_status = "reviewed"
    store.update_jobs(lambda jobs: jobs.with_listing_status((source, external_id), new_status))
    return RedirectResponse("/jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/jobs/refresh")
def refresh_jobs() -> Any:
    """The manual escape hatch: run the same pipeline the scheduled job runs."""
    run_pipeline()
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
