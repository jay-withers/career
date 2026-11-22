"""The registry of job-board adapters, indexed by the name used in
`settings().job_sources`.

Adding another source (Greenhouse/Lever/Ashby per-company boards, deferred
for now — see CLAUDE.md) means a new module with a `fetch(client,
preferences)` function and one new entry here, nothing else. Google and Reed
build their queries from `preferences`; a source that doesn't need it can
ignore it. Which of these run is `settings().job_sources`: a source left
registered but unlisted there costs nothing.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ..model import JobListing, JobPreferences
from . import google, reed

REGISTRY: dict[str, Callable[[httpx.Client, JobPreferences], list[JobListing]]] = {
    "google": google.fetch,
    "reed": reed.fetch,
}

# Sources whose search results carry only a snippet of each advert, and how
# to fetch the whole of one — None when it can't be fetched (no key). Google's
# results carry the whole advert already, so it has none.
DESCRIBERS: dict[str, Callable[[httpx.Client, JobListing], str | None]] = {
    "reed": reed.describe,
}

# Sources whose search returns only part of what they hold (a ranked top N
# that shifts between runs), so a listing missing from one run hasn't been
# withdrawn. pipeline._prune leaves these to STALE_AFTER.
PARTIAL: frozenset[str] = frozenset({"google"})
