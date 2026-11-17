"""`career backup`: the nightly encrypted copy of the profile to R2, and its proof
that it restores.

Adapted from finances' tests/test_backup.py.

R2 is an in-memory fake with the four S3 calls the job makes. The age keys are
real, so a test that passes here has actually encrypted and decrypted.
"""

from __future__ import annotations

import logging
import pathlib
from datetime import UTC, date, datetime
from typing import Any

import pyrage
import pytest
from pyrage import x25519

from career import backup, store
from career import settings as settings_module
from career.cli import main
from career.model import Profile, Role

OWNER = x25519.Identity.generate()
DRILL = x25519.Identity.generate()
BUCKET = "test-backups"

MID_MONTH = datetime(2026, 11, 15, 2, 30, 5, tzinfo=UTC)
DAILY = "daily/career/2026-11-15T023005Z/profile.json.age"
MONTHLY = "monthly/career/2026-11/profile.json.age"


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeR2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.listed: list[dict[str, Any]] = []
        # Armed by a test: rewrite what comes back, as a corrupted store would.
        self.tamper = False
        # Armed by a test: refuse uploads whose key contains this.
        self.refuse = ""

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        assert Bucket == BUCKET
        if self.refuse and self.refuse in Key:
            raise ConnectionError("R2 is having a day")
        self.puts.append(Key)
        self.objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == BUCKET
        data = self.objects[Key]
        if self.tamper:
            data = pyrage.encrypt(b"something else", [DRILL.to_public()])
        return {"Body": _Body(data)}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, MaxKeys: int) -> dict[str, Any]:
        assert Bucket == BUCKET
        self.listed.append({"Bucket": Bucket, "Prefix": Prefix, "MaxKeys": MaxKeys})
        keys = sorted(k for k in self.objects if k.startswith(Prefix))[:MaxKeys]
        return {"Contents": [{"Key": k} for k in keys]} if keys else {}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("BACKUP_BUCKET", BUCKET)
    monkeypatch.setenv("BACKUP_R2_ENDPOINT", "https://acc.eu.r2.cloudflarestorage.com")
    monkeypatch.setenv("BACKUP_AGE_RECIPIENT", str(OWNER.to_public()))
    # As Key Vault returns it when set from a file: with a trailing newline.
    monkeypatch.setenv("BACKUP_AGE_DRILL_KEY", f"{DRILL}\n")


@pytest.fixture
def r2() -> FakeR2:
    return FakeR2()


def _profile_path() -> pathlib.Path:
    return pathlib.Path(settings_module.settings().local_profile_path)


@pytest.fixture
def a_profile():
    role = Role(company="Acme", title="Engineer", started=date(2020, 1, 1))
    store.save_profile(Profile(roles=(role,)))
    return store.load_profile_raw()


def test_copies_the_profile_encrypted_and_the_owner_can_decrypt_it(configured, r2, a_profile):
    assert backup.run(client=r2, now=MID_MONTH) == 0

    sealed = r2.objects[DAILY]
    assert a_profile not in sealed
    assert pyrage.decrypt(sealed, [OWNER]) == a_profile


def test_the_drill_key_decrypts_it_too(configured, r2, a_profile):
    backup.run(client=r2, now=MID_MONTH)
    assert pyrage.decrypt(r2.objects[DAILY], [DRILL]) == a_profile


def test_the_first_run_in_a_month_also_keeps_a_monthly_copy(configured, r2, a_profile):
    assert backup.run(client=r2, now=MID_MONTH) == 0
    assert set(r2.objects) == {DAILY, MONTHLY}


def test_later_runs_that_month_keep_only_the_daily(configured, r2, a_profile):
    backup.run(client=r2, now=MID_MONTH)
    later = datetime(2026, 11, 16, 2, 30, tzinfo=UTC)
    backup.run(client=r2, now=later)
    assert r2.puts.count(MONTHLY) == 1
    assert "daily/career/2026-11-16T023000Z/profile.json.age" in r2.objects


def test_a_month_whose_first_run_failed_still_gets_its_monthly_copy(configured, r2, a_profile):
    r2.refuse = "career"
    assert backup.run(client=r2, now=datetime(2026, 12, 1, 2, 30, tzinfo=UTC)) == 1
    r2.refuse = ""
    assert backup.run(client=r2, now=datetime(2026, 12, 2, 2, 30, tzinfo=UTC)) == 0
    assert "monthly/career/2026-12/profile.json.age" in r2.objects


def test_a_rerun_adds_a_copy_and_never_replaces_one(configured, r2, a_profile):
    backup.run(client=r2, now=MID_MONTH)
    first = r2.objects[DAILY]
    _profile_path().write_bytes(b"{gone bad")
    backup.run(client=r2, now=datetime(2026, 11, 15, 14, 0, tzinfo=UTC))
    assert r2.objects[DAILY] == first
    assert r2.objects[MONTHLY] == first
    assert len(r2.puts) == len(set(r2.puts))


def test_a_missing_profile_fails(configured, r2, caplog):
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert "FAIL profile.json" in caplog.text
    assert r2.objects == {}


def test_a_copy_that_comes_back_different_fails(configured, r2, a_profile, caplog):
    r2.tamper = True
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert "differs" in caplog.text


def test_a_corrupt_profile_is_still_copied_then_fails(configured, r2, caplog):
    _profile_path().write_bytes(b"{not json")
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert pyrage.decrypt(r2.objects[DAILY], [OWNER]) == b"{not json"


def test_a_bad_copy_never_takes_the_months_slot(configured, r2, a_profile):
    """The monthly copy comes only from a daily copy that restored."""
    good = store.load_profile_raw()
    assert good is not None
    _profile_path().write_bytes(b"{not json")
    assert backup.run(client=r2, now=datetime(2026, 12, 1, 2, 45, tzinfo=UTC)) == 1
    assert "monthly/career/2026-12/profile.json.age" not in r2.objects

    _profile_path().write_bytes(good)
    assert backup.run(client=r2, now=datetime(2026, 12, 2, 2, 45, tzinfo=UTC)) == 0
    monthly = r2.objects["monthly/career/2026-12/profile.json.age"]
    assert pyrage.decrypt(monthly, [OWNER]) == good


def test_a_failed_monthly_lookup_still_keeps_the_daily(
    configured, r2, a_profile, monkeypatch, caplog
):
    def broken(**_: object) -> None:
        raise ConnectionError("R2 is having a day")

    monkeypatch.setattr(r2, "list_objects_v2", broken)
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert DAILY in r2.objects
    assert f"FAIL profile.json -> {MONTHLY}: ConnectionError" in caplog.text


def test_keys_rejects_a_malformed_drill_key_without_echoing_it(configured, monkeypatch):
    monkeypatch.setenv("BACKUP_AGE_DRILL_KEY", "AGE-SECRET-KEY-NOTAKEY")
    with pytest.raises(ValueError, match="BACKUP-AGE-DRILL-KEY is not") as raised:
        backup.keys()
    assert "NOTAKEY" not in str(raised.value)


def test_keys_rejects_a_malformed_recipient(configured, monkeypatch):
    monkeypatch.setenv("BACKUP_AGE_RECIPIENT", "age1nope")
    settings_module.settings.cache_clear()
    with pytest.raises(ValueError, match="BACKUP_AGE_RECIPIENT is not"):
        backup.keys()


@pytest.mark.parametrize("unset", ["BACKUP_BUCKET", "BACKUP_R2_ENDPOINT", "BACKUP_AGE_RECIPIENT"])
def test_refuses_to_run_half_configured(configured, r2, a_profile, monkeypatch, unset, caplog):
    monkeypatch.delenv(unset)
    settings_module.settings.cache_clear()
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert unset in caplog.text
    assert r2.objects == {}


def test_never_logs_a_key(configured, r2, a_profile, caplog):
    with caplog.at_level(logging.DEBUG):
        backup.run(client=r2, now=MID_MONTH)
    assert "AGE-SECRET-KEY" not in caplog.text


def test_check_bucket_lists_this_apps_prefix_and_writes_nothing(configured, r2):
    backup.check_bucket(r2)
    assert r2.listed == [{"Bucket": BUCKET, "Prefix": "daily/career/", "MaxKeys": 1}]
    assert r2.objects == {}


def test_r2_client_points_at_the_endpoint_with_the_vault_keys(configured, monkeypatch):
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "the-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "the-secret")
    client = backup.r2_client()
    assert client.meta.endpoint_url == "https://acc.eu.r2.cloudflarestorage.com"
    assert client.meta.region_name == "auto"


def test_is_dispatched_from_the_cli(monkeypatch):
    monkeypatch.setattr(backup, "run", lambda: 0)
    assert main(["backup"]) == 0


def test_a_failed_monthly_upload_is_counted_and_the_daily_still_kept(
    configured, r2, a_profile, caplog
):
    r2.refuse = "monthly/"
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert DAILY in r2.objects
    assert f"FAIL profile.json -> {MONTHLY}" in caplog.text


def test_an_unreadable_document_fails_the_run(configured, r2, monkeypatch, caplog):
    def broken() -> bytes | None:
        raise RuntimeError("blob down")

    monkeypatch.setattr(
        backup, "DOCUMENTS", (backup.Document("profile.json", broken, backup._profile, True),)
    )
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert "FAIL profile.json: RuntimeError" in caplog.text


def test_a_key_vault_error_is_reported_as_itself_not_as_a_bad_key(
    configured, r2, a_profile, monkeypatch, caplog
):
    """A drill key Key Vault can't hand over is not a malformed one."""
    monkeypatch.delenv("BACKUP_AGE_DRILL_KEY")
    with caplog.at_level(logging.INFO):
        assert backup.run(client=r2, now=MID_MONTH) == 1
    assert "FAIL setup: RuntimeError: BACKUP-AGE-DRILL-KEY is not set" in caplog.text
    assert "not an age secret key" not in caplog.text
    assert r2.objects == {}


def test_an_r2_client_that_cannot_be_built_is_logged_not_raised(
    configured, a_profile, monkeypatch, caplog
):
    def no_client() -> None:
        raise RuntimeError("R2-ACCESS-KEY-ID is not set")

    monkeypatch.setattr(backup, "r2_client", no_client)
    with caplog.at_level(logging.INFO):
        assert backup.run(now=MID_MONTH) == 1
    assert "FAIL setup: RuntimeError: R2-ACCESS-KEY-ID is not set" in caplog.text
