"""Synthetic profile and job-listing data, for local development only.

Not used by the deployed app or the daily pipeline — only `career seed` (see
cli.py) writes it, and only against the local-file fallback in store.py,
refusing to run at all if a blob container is configured. Its purpose is
that a fresh checkout's `make run` otherwise shows an empty profile and an
empty job queue, which is a poor way to look at the review queue, insights
or advancement pages. Every value below is invented for a fictional Senior
Platform Engineer career; none of it is the account owner's real history.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from .insights import generate_insights
from .matching import score_all
from .model import (
    AdvancementGuidance,
    Certification,
    JobListing,
    JobPreferences,
    JobsDocument,
    Profile,
    Role,
)


def synthetic_profile() -> Profile:
    """A fictional platform-engineering career, current role Senior Platform Engineer."""
    # Oldest first, matching how importer.py appends parsed history — the
    # profile page's own templates reverse this order for display, so
    # storing it any other way shows the current role at the bottom.
    roles = (
        Role(
            company="Aldergate Software",
            title="DevOps Engineer",
            started=date(2016, 9, 1),
            ended=date(2018, 5, 25),
            location="Cardiff, UK",
            employment_type="Full-time",
            description=(
                "Ran the build/release pipeline and Linux server estate for a small SaaS product."
            ),
            skills=("Linux", "Jenkins", "Bash", "AWS"),
        ),
        Role(
            company="Fenwick Digital",
            title="Platform Engineer",
            started=date(2018, 6, 1),
            ended=date(2021, 2, 26),
            location="Bristol, UK",
            employment_type="Full-time",
            description=(
                "Migrated a monolith's deployment pipeline onto Kubernetes and "
                "Terraform-managed AWS infrastructure; built the team's first "
                "CI/CD pipeline."
            ),
            skills=("AWS", "Docker", "CI/CD", "Terraform", "Python", "Linux"),
        ),
        Role(
            company="Northwind Systems",
            title="Senior Platform Engineer",
            started=date(2021, 3, 1),
            ended=None,
            location="Bristol, UK",
            employment_type="Full-time",
            description=(
                "Own the internal developer platform serving 40+ engineers: "
                "Kubernetes, Terraform-driven infrastructure, CI/CD pipelines and "
                "the on-call/observability stack behind them."
            ),
            skills=(
                "Kubernetes",
                "Terraform",
                "AWS",
                "CI/CD",
                "Docker",
                "Observability",
                "Python",
                "Go",
            ),
        ),
    )
    certifications = (
        Certification(
            name="AWS Certified Solutions Architect - Associate",
            issuing_org="Amazon Web Services",
            issued=date(2022, 4, 15),
            expires=date(2025, 4, 15),
            credential_id="AWS-SAA-EXAMPLE",
        ),
        Certification(
            name="Certified Kubernetes Administrator",
            issuing_org="Cloud Native Computing Foundation",
            issued=date(2023, 1, 10),
            expires=date(2026, 1, 10),
        ),
    )
    extra_skills = ("Leadership", "Mentoring", "System Design", "Site Reliability")
    preferences = JobPreferences(
        desired_titles=("Staff Platform Engineer", "Engineering Manager"),
        desired_locations=("Remote", "Southampton"),
        min_salary=65000,
        home_location="Fareham",
        max_distance_miles=30,
    )
    return Profile(
        roles=roles,
        certifications=certifications,
        extra_skills=extra_skills,
        preferences=preferences,
    )


# (external_id, title, company, location, url, description, days_ago,
#  status, salary_min, salary_max)
_SYNTHETIC_LISTINGS = (
    (
        "acme-co",
        "Staff Platform Engineer",
        "Acme Co",
        "Southampton, UK (Hybrid)",
        "https://example.com/jobs/acme-staff-platform-engineer",
        "Lead our internal developer platform: Kubernetes, Terraform and AWS, "
        "with a strong observability and CI/CD culture already in place.",
        2,
        "new",
        70000,
        90000,
    ),
    (
        "globex",
        "Senior Platform Engineer",
        "Globex Corp",
        "Remote (UK)",
        "https://example.com/jobs/globex-senior-platform-engineer",
        "Senior Platform Engineer role: Kubernetes, Terraform, Docker and Go, "
        "owning CI/CD for a fast-growing engineering org.",
        1,
        "reviewed",
        75000,
        95000,
    ),
    (
        "initech",
        "Cloud Infrastructure Lead",
        "Initech",
        "Glasgow, UK",
        "https://example.com/jobs/initech-cloud-infra-lead",
        "Lead our cloud infrastructure team: Kubernetes, Terraform, AWS, and "
        "mentoring a small platform team.",
        6,
        "new",
        90000,
        110000,
    ),
    (
        "soylent",
        "Site Reliability Engineer",
        "Soylent Ltd",
        "Remote (Europe)",
        "https://example.com/jobs/soylent-sre",
        "SRE role: Kubernetes, Docker, CI/CD and observability, on-call for a "
        "Python and Go platform.",
        3,
        "new",
        65000,
        80000,
    ),
    (
        "umbrella",
        "DevOps Engineer",
        "Umbrella Corp",
        "Cardiff, UK",
        "https://example.com/jobs/umbrella-devops-engineer",
        "DevOps Engineer to run our Jenkins pipelines and Linux server estate on AWS.",
        14,
        "dismissed",
        45000,
        55000,
    ),
    (
        "hooli",
        "Engineering Manager, Platform",
        "Hooli",
        "Remote (UK)",
        "https://example.com/jobs/hooli-em-platform",
        "Engineering Manager for a platform team running Kubernetes and Terraform "
        "on AWS — leadership and mentoring experience essential.",
        9,
        "applied",
        95000,
        120000,
    ),
)


def synthetic_jobs(profile: Profile) -> JobsDocument:
    """A job cache scored against `profile`, with insights and guidance filled in.

    Scoring and insights reuse the real `matching`/`insights` modules rather
    than hand-computing scores, so the seeded data stays consistent with
    whatever those modules do today. Only `guidance` is hand-written: it
    stands in for the one LLM call in the app (advancement.py), which needs
    a DeepSeek API key this local seed has no business requiring.
    """
    now = datetime.now(UTC)
    listings = tuple(
        JobListing(
            source="synthetic",
            external_id=row[0],
            title=row[1],
            company=row[2],
            location=row[3],
            url=row[4],
            description=row[5],
            posted_date=(now - timedelta(days=row[6])).date(),
            fetched_at=now,
            status=row[7],
            salary_min=row[8],
            salary_max=row[9],
        )
        for row in _SYNTHETIC_LISTINGS
    )
    scored = score_all(listings, profile)
    insights = generate_insights(scored, profile)
    guidance = AdvancementGuidance(
        generated_at=now,
        skill_gaps=(
            "Go at scale",
            "FinOps / infrastructure cost optimization",
            "Platform team leadership",
        ),
        suggested_next_roles=("Staff Platform Engineer", "Engineering Manager, Platform"),
        rationale=(
            "Synthetic guidance for local development. The real pipeline replaces this "
            "with a DeepSeek-generated analysis once DEEPSEEK_API_KEY is configured — see "
            "advancement.py."
        ),
    )
    return JobsDocument(listings=scored, insights=insights, guidance=guidance)
