"""The registry of job-board adapters, indexed by the name used in
`settings().job_sources`.

Adding a fourth source (Greenhouse/Lever/Ashby per-company boards, deferred
for now — see CLAUDE.md) means a new module with a `fetch(client)` function
and one new entry here, nothing else.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from ..model import JobListing
from . import adzuna, arbeitnow, remoteok

REGISTRY: dict[str, Callable[[httpx.Client], list[JobListing]]] = {
    "adzuna": adzuna.fetch,
    "remoteok": remoteok.fetch,
    "arbeitnow": arbeitnow.fetch,
}
