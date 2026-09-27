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
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    insights = MarketInsights(generated_at=datetime(2024, 1, 1, tzinfo=UTC), listing_count=0)

    assert generate_guidance(Profile(), insights) is None


def test_generate_guidance_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _Block:
        type = "text"
        text = json.dumps(
            {
                "skill_gaps": ["Kubernetes"],
                "suggested_next_roles": ["Staff Engineer"],
                "rationale": "Because reasons.",
            }
        )

    class _Response:
        def __init__(self) -> None:
            self.content = [_Block()]

    class _Messages:
        def create(self, **_kwargs: object) -> _Response:
            return _Response()

    class _FakeAnthropic:
        def __init__(self, **_kwargs: object) -> None:
            self.messages = _Messages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)

    insights = MarketInsights(generated_at=datetime(2024, 1, 1, tzinfo=UTC), listing_count=5)
    guidance = generate_guidance(Profile(), insights)

    assert guidance is not None
    assert guidance.skill_gaps == ("Kubernetes",)
    assert guidance.suggested_next_roles == ("Staff Engineer",)
    assert guidance.rationale == "Because reasons."


def test_generate_guidance_discards_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class _Block:
        type = "text"
        text = "not json"

    class _Response:
        def __init__(self) -> None:
            self.content = [_Block()]

    class _Messages:
        def create(self, **_kwargs: object) -> _Response:
            return _Response()

    class _FakeAnthropic:
        def __init__(self, **_kwargs: object) -> None:
            self.messages = _Messages()

    import anthropic

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)

    insights = MarketInsights(generated_at=datetime(2024, 1, 1, tzinfo=UTC), listing_count=5)

    assert generate_guidance(Profile(), insights) is None
