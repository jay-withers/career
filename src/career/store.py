"""Where the profile and the job cache live: two JSON blobs, each read whole
and written whole.

Adapted from jay-withers/gym-log src/gymlog/store.py. The blob client, the
lazy-import discipline and the ETag/retry mechanics are the same; this
version parametrizes over *which* document (profile or jobs) rather than
hard-coding one, since this app owns two.

**Concurrency.** One user and `max_replicas = 1`, so a lost update needs two
browser tabs — or a browser tab racing the scheduled pipeline job — to even
be possible. It is still guarded, because the cost is one header: every write
carries an `If-Match` on the ETag read at the start, and `update()` retries
once against the newer document.

With no container configured, each document falls back to a local file,
which is what makes `make run` and the test suite work against nothing but a
checkout.
"""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Callable

from .model import JobsDocument, Profile
from .settings import credential, settings

logger = logging.getLogger(__name__)


class ConflictError(RuntimeError):
    """The document changed between being read and being written."""


def load_profile() -> tuple[Profile, str | None]:
    cfg = settings()
    return _load(cfg.profile_container_url, "profile.json", cfg.local_profile_path, Profile)


def save_profile(profile: Profile, etag: str | None = None) -> str | None:
    return _save(
        settings().profile_container_url,
        "profile.json",
        settings().local_profile_path,
        profile.to_json(),
        etag,
    )


def update_profile(change: Callable[[Profile], Profile]) -> Profile:
    return _update(load_profile, save_profile, change)


def load_jobs() -> tuple[JobsDocument, str | None]:
    cfg = settings()
    return _load(cfg.jobs_container_url, "jobs.json", cfg.local_jobs_path, JobsDocument)


def save_jobs(jobs: JobsDocument, etag: str | None = None) -> str | None:
    return _save(
        settings().jobs_container_url,
        "jobs.json",
        settings().local_jobs_path,
        jobs.to_json(),
        etag,
    )


def update_jobs(change: Callable[[JobsDocument], JobsDocument]) -> JobsDocument:
    return _update(load_jobs, save_jobs, change)


def _load[T](
    container_url: str,
    blob_name: str,
    local_path: str,
    empty_type: type[T],
) -> tuple[T, str | None]:
    """Read a document and the ETag to write it back against.

    A blob (or local file) that has never existed yields an empty document
    and no ETag — that is a first run, not a failure. Every other error
    propagates.
    """
    blob = _blob(container_url, blob_name)
    if blob is None:
        path = pathlib.Path(local_path)
        if not path.exists():
            logger.info("no local %s yet; starting empty", local_path)
            return empty_type(), None
        return empty_type.from_json(path.read_text(encoding="utf-8")), None

    from azure.core.exceptions import ResourceNotFoundError

    try:
        stream = blob.download_blob()
        raw = stream.readall()
    except ResourceNotFoundError:
        logger.info("no %s blob yet; starting empty", blob_name)
        return empty_type(), None

    etag = stream.properties.etag
    return empty_type.from_json(raw.decode("utf-8")), etag


def _save(
    container_url: str,
    blob_name: str,
    local_path: str,
    body: str,
    etag: str | None,
) -> str | None:
    """Write a document, refusing to clobber one that moved underneath us.

    `etag` is the value from the `_load()` that produced this document. None
    means "this must be a create", which is what stops two first-runs racing
    and one of them winning silently.
    """
    blob = _blob(container_url, blob_name)
    if blob is None:
        path = pathlib.Path(local_path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(path)
        return None

    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

    encoded = body.encode("utf-8")
    try:
        if etag is None:
            result = blob.upload_blob(encoded, overwrite=False)
        else:
            result = blob.upload_blob(
                encoded,
                overwrite=True,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
    except (ResourceModifiedError, ResourceExistsError) as exc:
        raise ConflictError(f"{blob_name} changed while this write was being prepared") from exc

    return result.get("etag") if isinstance(result, dict) else None


def _update[T](
    load: Callable[[], tuple[T, str | None]],
    save: Callable[[T, str | None], str | None],
    change: Callable[[T], T],
) -> T:
    """Read, apply `change`, write — retrying once if the document moved.

    `change` must be pure and cheap: on a conflict it is called a second
    time against the newer document, so anything with a side effect would
    happen twice.
    """
    for attempt in (1, 2):
        document, etag = load()
        updated = change(document)
        try:
            save(updated, etag)
        except ConflictError:
            if attempt == 2:
                raise
            logger.warning("document changed under us, retrying against the newer one")
            continue
        return updated
    raise AssertionError("unreachable")


def _blob(container_url: str, blob_name: str):
    """A client for `blob_name` in `container_url`, or None when unconfigured.

    Imported lazily so the model and its tests never need the Azure SDK
    present — the same reason `settings.py` defers its Azure imports.
    """
    if not container_url:
        return None

    from azure.storage.blob import BlobClient

    url = f"{container_url.rstrip('/')}/{blob_name}"
    return BlobClient.from_blob_url(url, credential=credential())
