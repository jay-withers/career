"""The registry of job-board adapters, indexed by the name used in
`settings().job_sources`.

Adding another source (Greenhouse/Lever/Ashby per-company boards, deferred
for now — see CLAUDE.md) means a new module with a `fetch(client,
preferences)` function and one new entry here, nothing else. Most sources
ignore `preferences`; Reed builds its query from it.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ..model import JobListing, JobPreferences
from . import reed, remoteok

REGISTRY: dict[str, Callable[[httpx.Client, JobPreferences], list[JobListing]]] = {
    "reed": reed.fetch,
    "remoteok": remoteok.fetch,
}
