"""Configuration and secret resolution.

Copied from jay-withers/gym-log src/gymlog/settings.py, which took it from
repo-agent, which took it from market-agent. The secret-resolution machinery
below — `secret`, `optional_secret`, `_from_environment`,
`StaticTokenCredential`, `credential` and `dotenv` — is unchanged. Re-copy
rather than diverge; fix bugs in all four.

**This is the fourth consumer**, past the tripwire gym-log's own copy of this
docstring recorded ("a third consumer appears, *or* the same bug gets fixed
twice" — repo-agent, market-agent and gym-log already made three). The
decision written down there was to copy once more and extract a shared
library the next time the rule is tripped rather than pretend it wasn't; this
copy is that "once more". If a fifth consumer ever appears, or a bug in this
file needs fixing a second time, that's the point to actually extract it
rather than copy a fifth time.

Every secret is read from an environment variable first, then `.env`, and
only then from Key Vault. That ordering is what makes `make run` work locally
with no Azure involved, and it is why Terraform manages no Container Apps Key
Vault reference: a revision carrying one hard-fails if the secret is absent,
whereas this resolves at runtime and reports what is missing.

The name mapping is mechanical: `secret("APP-PASSCODE")` reads
`$APP_PASSCODE`, then `.env`, then the Key Vault secret named `APP-PASSCODE`.
Key Vault forbids underscores in names, environment variables conventionally
forbid hyphens, so one of the two has to be rewritten.
"""

from __future__ import annotations

import os
import time
from functools import cache, lru_cache
from typing import Any

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
    # passcode instead — see `api.deps._signing_key`, which explains why: a
    # per-process key would log the browser out on every deploy and every
    # scale-from-zero. Setting this decouples the two, so rotating the
    # passcode no longer invalidates outstanding sessions.
    cookie_secret: str = ""

    # Thirty days. This is a personal tool opened a few times a day; a login
    # prompt every visit is friction with no security benefit behind it.
    cookie_max_age_seconds: int = 60 * 60 * 24 * 30

    # Job-board sources to query in the daily pipeline. Comma-separated so it
    # can be trimmed without a code change; see sources/__init__.py for the
    # registry this indexes into.
    job_sources: str = "reed"

    log_level: str = Field(default="INFO")


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def dotenv() -> dict[str, str]:
    """`.env` as a plain dict, or empty when there is no such file.

    Read with the same parser `Settings` uses, so a value quoted for one is
    quoted for the other.

    Resolved relative to the working directory rather than to this file:
    `.env` belongs to whoever is running the command, and in the image there
    is none.
    """
    from dotenv import dotenv_values

    return {key: value for key, value in dotenv_values(".env").items() if value is not None}


@cache
def secret(name: str) -> str:
    """Resolve a secret by its hyphenated Key Vault name."""
    from_env = _from_environment(name)
    if from_env:
        return from_env

    uri = settings().key_vault_uri
    if not uri:
        raise RuntimeError(
            f"{name} is not set and no KEY_VAULT_URI is configured. "
            f"Set ${name.replace('-', '_').upper()} locally, or "
            f"`az keyvault secret set --name {name}` for a deployed environment."
        )

    # Imported here rather than at module scope so the model, the matcher and
    # the tests never need the Azure SDK installed or a credential.
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(vault_url=uri, credential=credential())
    return client.get_secret(name).value or ""


@cache
def optional_secret(name: str) -> str | None:
    """Resolve a secret that is allowed not to exist, returning None if it does not.

    **Absence is not the same as failure.** A missing env var, no vault
    configured, or a secret that is not in the vault all return None; an
    authentication or network error propagates, because "the credential is
    broken" must not look like "not configured". This is how optional
    job-board keys (Reed's) and the Anthropic API key degrade:
    the pipeline skips what it cannot reach rather than failing outright.
    """
    from_env = _from_environment(name)
    if from_env:
        return from_env

    uri = settings().key_vault_uri
    if not uri:
        return None

    from azure.core.exceptions import ResourceNotFoundError
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(vault_url=uri, credential=credential())
    try:
        return client.get_secret(name).value or None
    except ResourceNotFoundError:
        return None


def _from_environment(name: str) -> str | None:
    """A secret from the process environment, then `.env`.

    The real environment wins, so an inline `FOO=bar make run` overrides a
    checked-out `.env` rather than being silently ignored by it.
    """
    variable = name.replace("-", "_").upper()
    return os.environ.get(variable) or dotenv().get(variable)


# The scope a Key Vault data-plane token is issued for. `az` calls the same
# thing `--resource https://vault.azure.net`.
KEY_VAULT_SCOPE = "https://vault.azure.net/.default"


class StaticTokenCredential:
    """A credential wrapping one pre-fetched access token.

    Exists for the containerised local loop. The application image carries no
    `az`, so `DefaultAzureCredential` has nothing to fall back to. Passing a
    token in is strictly better than writing secrets to a `.env`: it expires
    in about an hour and is scoped to Key Vault alone.

    Never used in Azure, where the managed identity is available directly.
    """

    def __init__(self, token: str, scope: str = KEY_VAULT_SCOPE) -> None:
        self._token = token
        self._scope = scope
        # az does not report the expiry in a form worth parsing here, and the
        # SDK only uses this to decide whether to refresh — which this
        # credential cannot do. An hour matches the real lifetime; an expired
        # token then fails as a 401 from Key Vault, which is the honest
        # outcome.
        self._expires_on = int(time.time()) + 3600

    def _check(self, scopes: tuple[str, ...]) -> None:
        """Refuse a scope this token was not issued for."""
        if scopes and self._scope not in scopes:
            raise ValueError(f"this token is scoped to {self._scope}, not {', '.join(scopes)}")

    def get_token(self, *scopes: str, **_kwargs: Any) -> Any:
        from azure.core.credentials import AccessToken

        self._check(scopes)
        return AccessToken(self._token, self._expires_on)

    def get_token_info(self, *scopes: str, **_kwargs: Any) -> Any:
        """The newer protocol; some SDK versions call this instead."""
        from azure.core.credentials import AccessTokenInfo

        self._check(scopes)
        return AccessTokenInfo(self._token, self._expires_on)


@lru_cache(maxsize=1)
def credential():
    """The credential for Key Vault and Blob Storage.

    Three cases, in priority order:

    1. A pre-fetched Key Vault token from the environment — the containerised
       local loop, where there is no `az` to fall back to.
    2. The user-assigned identity, named explicitly. In Azure this must be
       explicit: `DefaultAzureCredential` would find the same identity
       eventually, but a workload with more than one identity attached picks
       unpredictably, and the failure looks like a permissions problem rather
       than a wrong-identity one.
    3. `DefaultAzureCredential`, which picks up a developer's `az login`.
    """
    cfg = settings()

    if cfg.azure_keyvault_token:
        return StaticTokenCredential(cfg.azure_keyvault_token)

    if cfg.azure_client_id:
        from azure.identity import ManagedIdentityCredential

        return ManagedIdentityCredential(client_id=cfg.azure_client_id)

    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()
