from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _client() -> TestClient:
    # Imported here, after conftest's fake_secrets fixture has set the
    # environment for this test — the module-level `app` in api.main resolves
    # settings() at import time in a couple of places (the lifespan hook).
    from career.api.main import app

    # https, not the TestClient default of http://testserver: the session
    # cookie is set `Secure` (deps.py), which an http-scheme client silently
    # refuses to send back — see jay-withers/gym-log's identical fixture.
    return TestClient(app, base_url="https://testserver")


def test_healthz_does_not_require_the_passcode() -> None:
    client = _client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_protected_page_redirects_to_login_when_unauthenticated() -> None:
    client = _client()

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_with_correct_passcode_sets_cookie_and_redirects() -> None:
    client = _client()

    response = client.post("/login", data={"passcode": "test-passcode"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "career_session" in response.cookies


def test_login_with_wrong_passcode_is_rejected() -> None:
    client = _client()

    response = client.post("/login", data={"passcode": "wrong"})

    assert response.status_code == 401


def test_profile_redirects_to_roles() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.get("/profile", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/roles"


def test_home_page_renders_once_authenticated() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.get("/")

    assert response.status_code == 200
    assert "Top new matches" in response.text


def test_editing_a_role_replaces_it_in_place() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})
    client.post(
        "/profile/roles",
        data={"company": "Acme", "title": "Engineer", "started": "2020-01-01"},
    )

    response = client.post(
        "/profile/roles/0",
        data={"company": "Acme", "title": "Senior Engineer", "started": "2020-01-01"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/roles"
    page = client.get("/profile/roles")
    assert "Senior Engineer" in page.text


def test_adding_and_removing_a_roles_skills_keeps_the_rest_of_the_role() -> None:
    from career import store

    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})
    client.post(
        "/profile/roles",
        data={"company": "Acme", "title": "Engineer", "started": "2020-01-01"},
    )
    client.post("/profile/skills/roles/0/add", data={"tag": "Go"})

    response = client.post(
        "/profile/skills/roles/0/add", data={"tag": " CI, CD "}, follow_redirects=False
    )
    client.post("/profile/skills/roles/0/add", data={"tag": "go"})  # duplicate, ignored
    client.post("/profile/skills/roles/0/remove", data={"tag": "Go"})

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/skills"
    profile, _ = store.load_profile()
    assert profile.roles[0].skills == ("CI, CD",)
    assert profile.roles[0].title == "Engineer"


def test_editing_skills_of_a_nonexistent_role_is_404() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post("/profile/skills/roles/0/add", data={"tag": "Go"})

    assert response.status_code == 404


def test_adding_and_removing_additional_skills() -> None:
    from career import store

    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    client.post("/profile/skills/extra/add", data={"tag": "Python"})
    client.post("/profile/skills/extra/add", data={"tag": "Kubernetes"})
    client.post("/profile/skills/extra/remove", data={"tag": "Python"})

    profile, _ = store.load_profile()
    assert profile.extra_skills == ("Kubernetes",)
    assert "Remove Kubernetes" in client.get("/profile/skills").text


def test_editing_a_role_keeps_its_skills() -> None:
    from career import store

    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})
    client.post(
        "/profile/roles",
        data={"company": "Acme", "title": "Engineer", "started": "2020-01-01"},
    )
    client.post("/profile/skills/roles/0/add", data={"tag": "Go"})

    client.post(
        "/profile/roles/0",
        data={"company": "Acme", "title": "Senior Engineer", "started": "2020-01-01"},
    )

    profile, _ = store.load_profile()
    assert profile.roles[0].title == "Senior Engineer"
    assert profile.roles[0].skills == ("Go",)


def test_editing_a_nonexistent_role_is_404() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post(
        "/profile/roles/0",
        data={"company": "Acme", "title": "Engineer", "started": "2020-01-01"},
    )

    assert response.status_code == 404


def test_refresh_insights_runs_the_pipeline_and_redirects_to_insights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr("career.api.routes.run_pipeline", lambda **kwargs: calls.append(kwargs))
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post("/insights/refresh", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/insights"
    # The Insights page's refresh is the one that regenerates guidance.
    assert calls == [{}]


def test_saving_preferences_round_trips() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post(
        "/profile/preferences",
        data={
            "work_arrangement": "hybrid",
            "min_salary": "65000",
            "home_location": "Fareham",
            "max_distance_miles": "30",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/preferences"
    page = client.get("/profile/preferences")
    assert '<option value="hybrid" selected>' in page.text
    assert 'value="65000"' in page.text
    assert 'value="Fareham"' in page.text
    assert 'value="30"' in page.text


def test_preference_keywords_are_tags_that_survive_saving_the_form() -> None:
    from career import store

    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post(
        "/profile/preferences/title-keywords/add",
        data={"tag": "Engineer, Platform"},
        follow_redirects=False,
    )
    client.post("/profile/preferences/title-keywords/add", data={"tag": "Staff Engineer"})
    client.post("/profile/preferences/title-keywords/remove", data={"tag": "Staff Engineer"})
    client.post("/profile/preferences/description-keywords/add", data={"tag": "Azure"})
    client.post("/profile/preferences/description-keywords/add", data={"tag": "AKS"})
    client.post("/profile/preferences/locations/add", data={"tag": "Southampton"})
    client.post("/profile/preferences/excluded-companies/add", data={"tag": "Globex, Inc."})
    client.post("/profile/preferences", data={"min_salary": "65000"})

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/preferences"
    prefs = store.load_profile()[0].preferences
    # A comma inside a title keyword is kept rather than splitting it in two.
    assert prefs.desired_titles == ("Engineer, Platform",)
    assert prefs.required_keywords == ("Azure", "AKS")
    assert prefs.desired_locations == ("Southampton",)
    assert prefs.excluded_companies == ("Globex, Inc.",)
    assert prefs.min_salary == 65000


def test_an_unknown_preference_tag_list_is_404() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post("/profile/preferences/nonsense/add", data={"tag": "x"})

    assert response.status_code == 404


def test_saving_preferences_with_blank_optional_fields_clears_them() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})
    client.post("/profile/preferences", data={"min_salary": "65000", "max_distance_miles": "30"})

    client.post("/profile/preferences", data={})

    page = client.get("/profile/preferences")
    assert "65000" not in page.text
    assert 'value="30"' not in page.text
    # An unset home_location falls back to the default rather than blanking.
    assert 'value="Fareham"' in page.text


def test_editing_a_certification_replaces_it_in_place() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})
    client.post("/profile/certifications", data={"name": "AZ-104", "issuing_org": "Microsoft"})

    response = client.post(
        "/profile/certifications/0",
        data={"name": "AZ-104", "issuing_org": "Microsoft Corp"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/certifications"
    page = client.get("/profile/certifications")
    assert "Microsoft Corp" in page.text


def test_refresh_jobs_skips_the_slow_guidance_step(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("career.api.routes.run_pipeline", lambda **kwargs: calls.append(kwargs))
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post("/jobs/refresh", follow_redirects=False)

    assert response.headers["location"] == "/jobs"
    assert calls == [{"with_guidance": False}]


def test_jobs_page_hides_excluded_listings_from_the_new_queue_unless_toggled() -> None:
    from datetime import UTC, datetime

    from career import store
    from career.model import JobListing, JobsDocument

    def listing(external_id: str, score: float, reasons: tuple[str, ...]) -> JobListing:
        return JobListing(
            source="reed",
            external_id=external_id,
            title=f"Job {external_id}",
            company="Acme",
            location="",
            url="",
            description="",
            posted_date=None,
            fetched_at=datetime.now(UTC),
            match_score=score,
            match_reasons=reasons,
        )

    store.save_jobs(
        JobsDocument(
            listings=(
                listing("1", 70.0, ("title matches",)),
                listing("2", 0.0, ("excluded: Zürich is outside the UK",)),
            )
        )
    )
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    page = client.get("/jobs")

    assert "Job 1" in page.text
    assert "Job 2" not in page.text
    assert "1 more excluded by your" in page.text
    home = client.get("/")
    assert "Job 1" in home.text
    assert "Job 2" not in home.text

    shown = client.get("/jobs?show_excluded=true")

    assert "Job 1" in shown.text
    assert "Job 2" in shown.text
    assert "Including 1 excluded by your" in shown.text
    assert "Hide excluded" in shown.text
