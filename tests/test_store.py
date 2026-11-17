"""Exercises the local-file fallback only — see conftest.fake_secrets, which
keeps PROFILE_CONTAINER_URL/JOBS_CONTAINER_URL empty for every test.
"""

from __future__ import annotations

from datetime import date

import pytest

from career import settings as settings_module
from career import store
from career.model import Profile, Role


def test_load_profile_with_no_local_file_yields_empty_document() -> None:
    profile, etag = store.load_profile()

    assert profile == Profile()
    assert etag is None


def test_update_profile_persists_across_loads() -> None:
    role = Role(company="Acme", title="Engineer", started=date(2020, 1, 1))

    store.update_profile(lambda p: p.with_role(role))
    reloaded, _ = store.load_profile()

    assert reloaded.roles == (role,)


def test_update_jobs_persists_across_loads() -> None:
    from datetime import UTC, datetime

    from career.model import JobListing

    listing = JobListing(
        source="reed",
        external_id="42",
        title="Engineer",
        company="Acme",
        location="Remote",
        url="https://example.com",
        description="",
        posted_date=None,
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )

    store.update_jobs(lambda j: j.with_listings((listing,)))
    reloaded, _ = store.load_jobs()

    assert reloaded.listings == (listing,)


class _FakeBlob:
    """Just the read a raw load makes."""

    def __init__(self, content: bytes | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error

    def download_blob(self) -> _FakeBlob:
        from azure.core.exceptions import ResourceNotFoundError

        if self.error is not None:
            raise self.error
        if self.content is None:
            raise ResourceNotFoundError("no such blob")
        return self

    def readall(self) -> bytes:
        assert self.content is not None
        return self.content


def _use_blob(monkeypatch: pytest.MonkeyPatch, blob: _FakeBlob) -> list[tuple[str, str]]:
    asked: list[tuple[str, str]] = []

    def fake(container_url: str, blob_name: str) -> _FakeBlob:
        asked.append((container_url, blob_name))
        return blob

    monkeypatch.setenv("PROFILE_CONTAINER_URL", "https://acct.blob.core.windows.net/profile")
    settings_module.settings.cache_clear()
    monkeypatch.setattr(store, "_blob", fake)
    return asked


def test_load_profile_raw_returns_the_blob_exactly_as_stored(monkeypatch) -> None:
    """The backup copies bytes, not this version's re-serialisation of them."""
    asked = _use_blob(monkeypatch, _FakeBlob(b'{"roles": [],  "odd spacing": 1}'))
    assert store.load_profile_raw() == b'{"roles": [],  "odd spacing": 1}'
    assert asked == [("https://acct.blob.core.windows.net/profile", "profile.json")]


def test_load_profile_raw_of_a_blob_that_never_existed_is_none(monkeypatch) -> None:
    _use_blob(monkeypatch, _FakeBlob())
    assert store.load_profile_raw() is None


def test_load_profile_raw_does_not_swallow_a_storage_error(monkeypatch) -> None:
    from azure.core.exceptions import HttpResponseError

    _use_blob(monkeypatch, _FakeBlob(error=HttpResponseError("storage is having a day")))
    with pytest.raises(HttpResponseError):
        store.load_profile_raw()


def test_load_profile_raw_reads_the_local_file_without_a_container() -> None:
    assert store.load_profile_raw() is None
    store.save_profile(Profile())
    assert store.load_profile_raw() == Profile().to_json().encode("utf-8")
