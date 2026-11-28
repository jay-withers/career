from __future__ import annotations

import pytest
from appkit import csrf
from fastapi.testclient import TestClient


def login_data(client: TestClient, passcode: str) -> dict[str, str]:
    """What the login form posts: the passcode and the page's CSRF token."""
    return {"passcode": passcode, "csrf_token": csrf.token_in(client.get("/login").text)}


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


def test_healthz_reports_the_deployed_image_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """`make smoke` reads this to prove the new revision is the one serving."""
    monkeypatch.setenv("IMAGE_TAG", "v1.2.3")

    assert _client().get("/healthz").json()["version"] == "v1.2.3"


def test_readyz_reads_the_profile() -> None:
    """Ready when the profile loads: an empty local one counts."""
    response = _client().get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "storage": True}


def test_readyz_is_503_when_the_profile_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    from career import store

    def unreadable() -> None:
        raise RuntimeError("blob down")

    monkeypatch.setattr(store, "load_profile", unreadable)

    assert _client().get("/readyz").status_code == 503


def test_protected_page_redirects_to_login_when_unauthenticated() -> None:
    client = _client()

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_with_correct_passcode_sets_cookie_and_redirects() -> None:
    client = _client()

    response = client.post(
        "/login", data=login_data(client, "test-passcode"), follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "career_session" in response.cookies


def test_login_with_wrong_passcode_is_rejected() -> None:
    client = _client()

    response = client.post("/login", data=login_data(client, "wrong"))

    assert response.status_code == 401


def test_profile_redirects_to_roles() -> None:
    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))

    response = client.get("/profile", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/profile/roles"


def test_home_page_renders_once_authenticated() -> None:
    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))

    response = client.get("/")

    assert response.status_code == 200
    assert "Top new matches" in response.text


def test_editing_a_role_replaces_it_in_place() -> None:
    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))
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
    client.post("/login", data=login_data(client, "test-passcode"))
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
    client.post("/login", data=login_data(client, "test-passcode"))

    response = client.post("/profile/skills/roles/0/add", data={"tag": "Go"})

    assert response.status_code == 404


def test_adding_and_removing_additional_skills() -> None:
    from career import store

    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))

    client.post("/profile/skills/extra/add", data={"tag": "Python"})
    client.post("/profile/skills/extra/add", data={"tag": "Kubernetes"})
    client.post("/profile/skills/extra/remove", data={"tag": "Python"})

    profile, _ = store.load_profile()
    assert profile.extra_skills == ("Kubernetes",)
    assert "Remove Kubernetes" in client.get("/profile/skills").text


def test_editing_a_role_keeps_its_skills() -> None:
    from career import store

    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))
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
    client.post("/login", data=login_data(client, "test-passcode"))

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
    client.post("/login", data=login_data(client, "test-passcode"))

    response = client.post("/insights/refresh", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/insights"
    # The Insights page's refresh is the one that regenerates guidance.
    assert calls == [{}]


def test_saving_preferences_round_trips() -> None:
    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))

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
    client.post("/login", data=login_data(client, "test-passcode"))

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
    client.post("/login", data=login_data(client, "test-passcode"))

    response = client.post("/profile/preferences/nonsense/add", data={"tag": "x"})

    assert response.status_code == 404


def test_saving_preferences_with_blank_optional_fields_clears_them() -> None:
    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))
    client.post("/profile/preferences", data={"min_salary": "65000", "max_distance_miles": "30"})

    client.post("/profile/preferences", data={})

    page = client.get("/profile/preferences")
    assert "65000" not in page.text
    assert 'value="30"' not in page.text
    # An unset home_location falls back to the default rather than blanking.
    assert 'value="Fareham"' in page.text


def test_editing_a_certification_replaces_it_in_place() -> None:
    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))
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
    client.post("/login", data=login_data(client, "test-passcode"))

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
    client.post("/login", data=login_data(client, "test-passcode"))

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


def test_manifest_is_public_and_names_android_icons() -> None:
    """A fresh install starts on the login page, before any cookie exists;
    Android Chrome wants a raster icon of at least 192px and a maskable one."""
    response = _client().get("/manifest.json")
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["display"] == "standalone"
    # The installed app opens on the home page, and keeps its identity if that moves.
    assert manifest["start_url"] == "/"
    assert manifest["id"] == "/"
    assert {(i["sizes"], i["purpose"]) for i in manifest["icons"]} == {
        ("192x192", "any"),
        ("512x512", "any"),
        ("512x512", "maskable"),
    }


def test_manifest_icons_are_served_without_the_passcode() -> None:
    client = _client()
    for icon in client.get("/manifest.json").json()["icons"]:
        response = client.get(icon["src"])
        assert response.status_code == 200, icon["src"]
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")


def test_login_page_links_the_manifest() -> None:
    assert '<link rel="manifest" href="/manifest.json">' in _client().get("/login").text


# --- refused input ---------------------------------------------------------------


def _signed_in() -> TestClient:
    client = _client()
    client.post("/login", data=login_data(client, "test-passcode"))
    return client


def _profile_bytes() -> bytes | None:
    from career import store

    return store.load_profile_raw()


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        ({"started": "2020-01-01", "ended": "2019-12-31"}, "A role can't end before it starts."),
        ({"started": "last spring"}, "Started isn't a date (YYYY-MM-DD)."),
        ({"started": "2020-01-01", "ended": "soon"}, "Ended isn't a date (YYYY-MM-DD)."),
        ({"started": "   "}, "Started is required."),
    ],
)
def test_a_role_with_bad_dates_is_refused_and_nothing_written(data, detail) -> None:
    client = _signed_in()
    before = _profile_bytes()
    response = client.post(
        "/profile/roles",
        data={"company": "Acme", "title": "Engineer", **data},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert _profile_bytes() == before


def test_editing_a_role_to_end_before_it_starts_is_refused() -> None:
    from datetime import date

    from career import store
    from career.model import Profile, Role

    store.save_profile(
        Profile(roles=(Role(company="Acme", title="Engineer", started=date(2020, 1, 1)),))
    )
    before = _profile_bytes()
    response = _signed_in().post(
        "/profile/roles/0",
        data={
            "company": "Acme",
            "title": "Engineer",
            "started": "2020-01-01",
            "ended": "2019-01-01",
        },
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert _profile_bytes() == before


def test_a_certification_that_expires_before_it_was_issued_is_refused() -> None:
    before = _profile_bytes()
    response = _signed_in().post(
        "/profile/certifications",
        data={"name": "AZ-104", "issued": "2024-05-01", "expires": "2024-04-01"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "A certification can't expire before it was issued."}
    assert _profile_bytes() == before


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        ({"min_salary": "nan"}, "Minimum salary must be zero or more."),
        ({"min_salary": "-5"}, "Minimum salary must be zero or more."),
        ({"min_salary": "lots"}, "Minimum salary isn't a number."),
        ({"max_distance_miles": "inf"}, "Maximum distance must be zero or more."),
    ],
)
def test_a_preference_number_that_isnt_one_is_refused(data, detail) -> None:
    before = _profile_bytes()
    response = _signed_in().post("/profile/preferences", data=data, follow_redirects=False)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert _profile_bytes() == before


def test_good_preferences_still_save() -> None:
    from career import store

    response = _signed_in().post(
        "/profile/preferences",
        data={"min_salary": "60000", "max_distance_miles": "25"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    preferences = store.load_profile()[0].preferences
    assert (preferences.min_salary, preferences.max_distance_miles) == (60000.0, 25.0)


def test_a_write_the_store_refuses_is_a_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """The backstop: a route bug the form checks missed is refused at save."""
    monkeypatch.setattr(
        "career.integrity.check_profile",
        lambda p: ["roles[0]: ends before it starts"] if p.roles else [],
    )
    response = _signed_in().post(
        "/profile/roles",
        data={"company": "Acme", "title": "Engineer", "started": "2020-01-01"},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Not saved: 1 problem(s): roles[0]: ends before it starts"


def test_a_login_without_the_csrf_token_is_refused_even_with_the_passcode():
    client = _client()
    client.get("/login")
    response = client.post("/login", data={"passcode": "test-passcode"}, follow_redirects=False)
    assert response.status_code == 403
    assert "expired" in response.text
    # The re-render carries a token that works, so a retry signs in.
    retry = {"passcode": "test-passcode", "csrf_token": csrf.token_in(response.text)}
    assert client.post("/login", data=retry, follow_redirects=False).status_code == 303


def test_a_browser_that_keeps_no_cookie_is_told_cookies_are_needed():
    client = _client()
    token = csrf.token_in(client.get("/login").text)
    client.cookies.clear()
    data = {"passcode": "test-passcode", "csrf_token": token}
    response = client.post("/login", data=data, follow_redirects=False)
    assert response.status_code == 403
    assert "needs cookies" in response.text


def test_a_cross_site_post_is_refused():
    client = _client()
    response = client.post(
        "/login",
        data=login_data(client, "test-passcode"),
        headers={"Sec-Fetch-Site": "cross-site"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "content-security-policy" in response.headers


# --- the release in the header ------------------------------------------------


def test_a_signed_in_page_shows_the_release_beside_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMAGE_TAG", "v1.2.3")
    page = _signed_in().get("/")
    # The signed-in home page, not a followed redirect to /login.
    assert (page.status_code, page.url.path) == (200, "/")
    assert '<span class="version">v1.2.3</span>' in page.text


@pytest.mark.parametrize("tag", [None, "", "  "])
def test_no_release_is_shown_when_none_is_deployed(
    monkeypatch: pytest.MonkeyPatch, tag: str | None
) -> None:
    """A local `make run` has no IMAGE_TAG; it shows nothing rather than a blank tag."""
    if tag is None:
        monkeypatch.delenv("IMAGE_TAG", raising=False)
    else:
        monkeypatch.setenv("IMAGE_TAG", tag)
    page = _signed_in().get("/")
    # The signed-in home page, not a followed redirect to /login.
    assert (page.status_code, page.url.path) == (200, "/")
    assert 'class="version"' not in page.text


# --- last updated beside "Refresh now" -------------------------------------------


@pytest.mark.parametrize("page", ["/", "/jobs", "/insights"])
def test_refresh_button_shows_when_the_pipeline_last_ran(page: str) -> None:
    from datetime import UTC, datetime

    from career import store
    from career.model import JobsDocument, MarketInsights

    store.save_jobs(
        JobsDocument(insights=MarketInsights(generated_at=datetime(2026, 11, 2, 6, 5, tzinfo=UTC)))
    )

    text = _signed_in().get(page).text

    assert (
        '<time class="muted small" datetime="2026-11-02T06:05:00+00:00">'
        "Last updated 2 Nov 2026, 06:05 UTC</time>"
    ) in text


@pytest.mark.parametrize("page", ["/", "/jobs", "/insights"])
def test_refresh_button_says_when_the_pipeline_never_ran(page: str) -> None:
    from career import store
    from career.model import JobsDocument

    store.save_jobs(JobsDocument())

    assert "Not refreshed yet" in _signed_in().get(page).text


def test_utc_time_converts_before_labelling_it_utc() -> None:
    from datetime import datetime, timedelta, timezone

    from career.api.routes import utc_time

    one_hour_ahead = datetime(2026, 11, 2, 7, 5, tzinfo=timezone(timedelta(hours=1)))

    assert utc_time(one_hour_ahead) == "2 Nov 2026, 06:05 UTC"
    assert utc_time(one_hour_ahead, "%H:%M") == "06:05 UTC"
