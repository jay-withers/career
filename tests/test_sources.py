from __future__ import annotations

import httpx
import pytest
import respx

from career.sources import adzuna, arbeitnow, remoteok


@respx.mock
def test_adzuna_fetch_returns_empty_without_keys() -> None:
    with httpx.Client() as client:
        assert adzuna.fetch(client) == []
    # No request should have been attempted at all.
    assert not respx.calls.called


@respx.mock
def test_adzuna_fetch_normalizes_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    from career import settings as settings_module

    settings_module.optional_secret.cache_clear()

    respx.get(url__regex=r"https://api\.adzuna\.com/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "1",
                        "title": "Engineer",
                        "company": {"display_name": "Acme"},
                        "location": {"display_name": "London"},
                        "redirect_url": "https://example.com/1",
                        "description": "Build things.",
                        "created": "2024-01-01T00:00:00Z",
                    }
                ]
            },
        )
    )

    with httpx.Client() as client:
        listings = adzuna.fetch(client)

    assert len(listings) == 1
    assert listings[0].source == "adzuna"
    assert listings[0].company == "Acme"


@respx.mock
def test_remoteok_fetch_skips_the_leading_legal_notice() -> None:
    respx.get(remoteok.URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"legal": "notice"},
                {
                    "id": "1",
                    "position": "Engineer",
                    "company": "Acme",
                    "location": "Remote",
                    "url": "https://example.com/1",
                    "description": "Build things.",
                    "date": "2024-01-01T00:00:00",
                },
            ],
        )
    )

    with httpx.Client() as client:
        listings = remoteok.fetch(client)

    assert len(listings) == 1
    assert listings[0].source == "remoteok"


@respx.mock
def test_arbeitnow_fetch_normalizes_results() -> None:
    respx.get(arbeitnow.URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "slug": "acme-engineer",
                        "title": "Engineer",
                        "company_name": "Acme",
                        "location": "Berlin",
                        "url": "https://example.com/1",
                        "description": "Build things.",
                        "created_at": 1704067200,
                        "remote": False,
                    }
                ]
            },
        )
    )

    with httpx.Client() as client:
        listings = arbeitnow.fetch(client)

    assert len(listings) == 1
    assert listings[0].source == "arbeitnow"
    assert listings[0].external_id == "acme-engineer"
