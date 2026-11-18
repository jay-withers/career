"""`career selfcheck`, which `make smoke` runs in every job after a deploy.

It has to fail on exactly what would break a real run, and do nothing else: a
false failure rolls back a good release, and a side effect would fire on every
deploy.
"""

from __future__ import annotations

import logging

import pytest

from career import selfcheck, store
from career.cli import main


@pytest.fixture
def storage_ok(monkeypatch):
    monkeypatch.setattr(store, "load_profile", lambda: (None, None))
    monkeypatch.setattr(store, "load_jobs", lambda: (None, None))


def test_passes_when_the_storage_reads(storage_ok):
    assert selfcheck.run() == 0


def test_fails_when_either_document_cannot_be_read(storage_ok, monkeypatch, caplog):
    def broken():
        raise RuntimeError("blob down")

    monkeypatch.setattr(store, "load_jobs", broken)
    with caplog.at_level(logging.INFO):
        assert selfcheck.run() == 1
    assert "FAIL storage: jobs" in caplog.text


def test_never_logs_a_secret_value(storage_ok, monkeypatch, caplog):
    monkeypatch.setenv("REED_API_KEY", "value-of-secret")
    with caplog.at_level(logging.DEBUG):
        selfcheck.run()
    assert "value-of-secret" not in caplog.text


def test_is_dispatched_from_the_cli(monkeypatch):
    monkeypatch.setattr(selfcheck, "run", lambda: 0)
    assert main(["selfcheck"]) == 0


@pytest.fixture
def backup_job(monkeypatch):
    """What the backup job is given: a bucket, and its three secrets."""
    from pyrage import x25519

    from career import backup

    monkeypatch.setenv("BACKUP_BUCKET", "test-backups")
    monkeypatch.setenv("BACKUP_R2_ENDPOINT", "https://acc.eu.r2.cloudflarestorage.com")
    monkeypatch.setenv("BACKUP_AGE_RECIPIENT", str(x25519.Identity.generate().to_public()))
    for name in selfcheck.BACKUP_SECRETS:
        monkeypatch.setenv(name.replace("-", "_"), "value-of-secret")
    monkeypatch.setenv("BACKUP_AGE_DRILL_KEY", str(x25519.Identity.generate()))
    calls: list[str] = []
    monkeypatch.setattr(backup.JOB, "check_bucket", lambda: calls.append("listed"))
    return calls


def test_the_backup_job_also_checks_its_keys_and_bucket(storage_ok, backup_job, caplog):
    with caplog.at_level(logging.INFO):
        assert selfcheck.run() == 0
    assert backup_job == ["listed"]
    assert "ok secret BACKUP-AGE-DRILL-KEY" in caplog.text
    assert "ok backup bucket" in caplog.text
    assert "ok backup settings and keys" in caplog.text


def test_the_backup_job_fails_without_its_drill_key(storage_ok, backup_job, monkeypatch, caplog):
    """The finances deploy that rolled back: R2 keys set, drill key never added."""
    monkeypatch.delenv("BACKUP_AGE_DRILL_KEY")
    with caplog.at_level(logging.INFO):
        assert selfcheck.run() == 1
    assert "FAIL secret BACKUP-AGE-DRILL-KEY" in caplog.text


def test_the_backup_job_fails_on_an_unset_endpoint(storage_ok, backup_job, monkeypatch, caplog):
    monkeypatch.delenv("BACKUP_R2_ENDPOINT")
    with caplog.at_level(logging.INFO):
        assert selfcheck.run() == 1
    assert "FAIL backup settings and keys: ValueError: not configured, BACKUP_R2_ENDPOINT" in (
        caplog.text
    )


def test_settings_that_dont_load_are_reported_not_raised(storage_ok, monkeypatch, caplog):
    from functools import cache

    from career import settings as settings_module

    # Cached like the real one, so the suite's teardown can clear it.
    @cache
    def broken() -> None:
        raise ValueError("bad setting")

    monkeypatch.setattr(settings_module, "settings", broken)
    with caplog.at_level(logging.INFO):
        assert selfcheck.run() == 1
    assert "FAIL settings: ValueError: bad setting" in caplog.text


def test_the_backup_job_fails_without_its_r2_keys(storage_ok, backup_job, monkeypatch, caplog):
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY")
    with caplog.at_level(logging.INFO):
        assert selfcheck.run() == 1
    assert "FAIL secret R2-SECRET-ACCESS-KEY" in caplog.text


def test_the_other_jobs_need_neither_the_bucket_nor_the_backup_keys(storage_ok, caplog):
    with caplog.at_level(logging.INFO):
        assert selfcheck.run() == 0
    assert "backup bucket" not in caplog.text
    assert "R2-" not in caplog.text
