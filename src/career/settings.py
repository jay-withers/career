"""Configuration and secret resolution.

`Settings` is this app's own. Secret resolution comes from jay-withers/appkit
(`appkit.keyvault`), which replaced the copies of it in market-agent,
repo-agent, gym-log, finances and career; fix a bug there, once. The wrappers
below bind it to these settings and cache it, so a test can clear them.

Every secret is read from an environment variable first, then `.env`, and only
then from Key Vault. That ordering is what makes `make run` work locally with no
Azure involved, and it is why Terraform manages no Container Apps Key Vault
reference: a revision carrying one hard-fails if the secret is absent, whereas
this resolves at runtime and reports what is missing.

The name mapping is mechanical: `secret("APP-PASSCODE")` reads `$APP_PASSCODE`,
then `.env`, then the Key Vault secret named `APP-PASSCODE`.
"""

from __future__ import annotations

from functools import cache, lru_cache
from typing import Any

from appkit import keyvault

# Re-exported: the tests (and conftest's cache clearing) reach them here.
from appkit.keyvault import KEY_VAULT_SCOPE as KEY_VAULT_SCOPE
from appkit.keyvault import StaticTokenCredential as StaticTokenCredential
from appkit.keyvault import dotenv as dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Non-secret configuration. Anything in this class is safe in a log line."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"

    key_vault_uri: str = ""
    # The managed identity's client id. Empty locally, which is the signal to
    # fall back to DefaultAzureCredential.
    azure_client_id: str = ""
    # A pre-fetched Key Vault access token, for a container that has no `az`.
    azure_keyvault_token: str = ""

    applicationinsights_connection_string: str = ""

    # Blob containers holding the career profile and the cached job listings
    # respectively. Not secrets: they are URLs, and reaching them still needs
    # the managed identity's RBAC grant on each container. Empty means "use
    # the local file instead" — see store.py — which is what makes `make run`
    # and the test suite work with no Azure involved.
    profile_container_url: str = ""
    jobs_container_url: str = ""

    # Where each document goes when no container is configured. Only ever
    # used locally.
    local_profile_path: str = ".career-profile.json"
    local_jobs_path: str = ".career-jobs.json"

    # The passcode gate is on unless explicitly disabled. It defaults *on* so
    # that forgetting to configure it fails closed — this is reachable from
    # the public internet the moment ingress is external.
    require_passcode: bool = True

    # Signs the session cookie. Absent means the key is derived from the
    # passcode instead (see `appkit.passcode`'s `signing_key`), because a
    # per-process key would log the browser out on every deploy and every
    # scale-from-zero. Setting this decouples the two, so rotating the
    # passcode no longer invalidates outstanding sessions.
    cookie_secret: str = ""

    # Thirty days. This is a personal tool opened a few times a day; a login
    # prompt every visit is friction with no security benefit behind it.
    cookie_max_age_seconds: int = 60 * 60 * 24 * 30

    # Job-board sources to query in the pipeline. Comma-separated so it can be
    # changed without a code change; see sources/__init__.py for the registry
    # this indexes into. Google (through SerpApi) covers Reed's adverts as
    # well as Indeed's and employers' own sites, so Reed is off by default;
    # "google,reed" turns it back on.
    job_sources: str = "google"

    # The most SerpApi searches the Google source spends in a month, out of
    # the free plan's 250 (see sources/google.py). The pipeline runs twice a
    # week (terraform/main.container-apps-job.tf), about 9 runs a month, at
    # two searches per desired title per run; the margin is for "refresh
    # now" and trying a key out by hand.
    google_jobs_monthly_searches: int = 200
    # And at most this many in one run, so the month's first runs (and any
    # "refresh now") can't spend what its last ones need. Two pages for each
    # of up to ten titles; 9 runs a month at this is 180.
    google_jobs_searches_per_run: int = 20

    # The weekly digest (see digest.py). The sender must be on a domain
    # verified in Resend; the recipient is a secret (DIGEST-TO), not a
    # setting, only so that a personal address stays out of this public
    # repository and its Terraform.
    digest_from: str = "career <digest@career.jaywithers.uk>"
    # Linked from the digest, so it can open the app.
    app_url: str = "https://career.jaywithers.uk"

    # The nightly off-Azure backup (`career backup`, see backup.py). Only the
    # backup job is given these. The recipient is the owner's age public key,
    # whose private half stays offline; the R2 keys and the drill key are
    # secrets, resolved by name in backup.py.
    backup_bucket: str = ""
    backup_r2_endpoint: str = ""
    backup_age_recipient: str = ""

    log_level: str = Field(default="INFO")


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()


@cache
def secret(name: str) -> str:
    """Resolve a secret by its hyphenated Key Vault name, raising if it is absent."""
    return keyvault.resolve(name, key_vault_uri=settings().key_vault_uri, credential=credential)


@cache
def optional_secret(name: str) -> str | None:
    """Resolve a secret that is allowed not to exist, returning None if it does not.

    An authentication or network error still raises: "the credential is broken"
    must not look like "not configured".
    """
    return keyvault.resolve_optional(
        name, key_vault_uri=settings().key_vault_uri, credential=credential
    )


@lru_cache(maxsize=1)
def credential() -> Any:
    """The credential for Key Vault and Blob Storage (`appkit.keyvault.make_credential`)."""
    cfg = settings()
    return keyvault.make_credential(
        keyvault_token=cfg.azure_keyvault_token, client_id=cfg.azure_client_id
    )
