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


def test_home_page_renders_once_authenticated() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.get("/")

    assert response.status_code == 200
    assert "Overview" in response.text


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
    monkeypatch.setattr("career.api.routes.run_pipeline", lambda: calls.append(1))
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post("/insights/refresh", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/insights"
    assert calls == [1]


def test_saving_preferences_round_trips() -> None:
    client = _client()
    client.post("/login", data={"passcode": "test-passcode"})

    response = client.post(
        "/profile/preferences",
        data={
            "desired_titles": "Staff Engineer, Principal Engineer",
            "desired_locations": "Remote",
            "remote_only": "on",
            "excluded_companies": "Globex",
            "min_salary": "65000",
            "home_location": "Fareham",
            "max_distance_miles": "30",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/preferences"
    page = client.get("/profile/preferences")
    assert "Staff Engineer, Principal Engineer" in page.text
    assert "Globex" in page.text
    assert "checked" in page.text
    assert 'value="65000"' in page.text
    assert 'value="Fareham"' in page.text
    assert 'value="30"' in page.text


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
