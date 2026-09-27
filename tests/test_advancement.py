from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from career.advancement import generate_guidance
from career.model import MarketInsights, Profile


def test_generate_guidance_skips_without_api_key() -> None:
    insights = MarketInsights(generated_at=datetime(2024, 1, 1, tzinfo=UTC), listing_count=10)

    assert generate_guidance(Profile(), insights) is None


def test_generate_guidance_skips_with_no_listings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    insights = MarketInsights(generated_at=datetime(2024, 1, 1, tzinfo=UTC), listing_count=0)

    assert generate_guidance(Profile(), insights) is None


def _mock_deepseek_response(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    """Stub `urllib.request.urlopen` so no real HTTP call is attempted."""

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    def _fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        return _Response()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)


def test_generate_guidance_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _mock_deepseek_response(
        monkeypatch,
        json.dumps(
            {
                "skill_gaps": ["Kubernetes"],
                "suggested_next_roles": ["Staff Engineer"],
                "rationale": "Because reasons.",
            }
        ),
    )

    insights = MarketInsights(generated_at=datetime(2024, 1, 1, tzinfo=UTC), listing_count=5)
    guidance = generate_guidance(Profile(), insights)

    assert guidance is not None
    assert guidance.skill_gaps == ("Kubernetes",)
    assert guidance.suggested_next_roles == ("Staff Engineer",)
    assert guidance.rationale == "Because reasons."


def test_generate_guidance_discards_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _mock_deepseek_response(monkeypatch, "not json")

    insights = MarketInsights(generated_at=datetime(2024, 1, 1, tzinfo=UTC), listing_count=5)

    assert generate_guidance(Profile(), insights) is None
