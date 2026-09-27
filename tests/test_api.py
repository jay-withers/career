from __future__ import annotations

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
