"""One entrypoint — `career serve|pipeline|show|seed`.

`serve` is the web application; `pipeline` is what the scheduled Container
Apps Job runs (and what the app's "refresh now" button also calls,
in-process — see api/routes.py). `show` is an operator command that runs
against the real blobs, so it needs `PROFILE_CONTAINER_URL`/
`JOBS_CONTAINER_URL` and a credential with `Storage Blob Data Contributor` on
each container — which whoever applied the Terraform already has. `seed` is
the opposite: it refuses to run unless those two variables are *unset*,
since it writes invented data (see seed.py) to the local-file fallback for
local development, and must never be able to reach the real blobs.

Note Terraform deliberately sets **no** `command`: the Dockerfile's
`ENTRYPOINT` names this console script, and duplicating that name in
Terraform creates a second source of truth. See
terraform/main.container-apps.tf's comment for the outage that taught this
in jay-withers/gym-log; `args` picks the subcommand.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from . import telemetry
from .settings import settings


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings().log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        stream=sys.stdout,
    )
    for noisy in (
        "httpx",
        "httpcore",
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.identity",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _terminate(signum: int, _frame: object) -> None:
    """Turn SIGTERM into an exception so `finally` blocks run.

    Container Apps sends SIGTERM before SIGKILL when a replica is scaled
    down — which, at `min_replicas = 0`, happens after every visit. Without
    this the default disposition kills the process outright and buffered
    telemetry goes with it.
    """
    raise SystemExit(f"terminated by signal {signum}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="career")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web application")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="reload on edit, for local work")

    sub.add_parser("pipeline", help="fetch listings, match, regenerate insights and guidance")

    sub.add_parser("show", help="print the profile and job cache as JSON")

    seed = sub.add_parser(
        "seed", help="write synthetic profile and job data, for local development"
    )
    seed.add_argument(
        "--force", action="store_true", help="overwrite an existing local profile or job cache"
    )

    args = parser.parse_args(argv)

    _configure_logging()
    # Before the app is imported: the instrumentation patches FastAPI.__init__.
    telemetry.configure(args.command)
    signal.signal(signal.SIGTERM, _terminate)

    try:
        if args.command == "serve":
            return _serve(args)
        if args.command == "pipeline":
            return _pipeline()
        if args.command == "show":
            return _show()
        if args.command == "seed":
            return _seed(args)
    finally:
        telemetry.flush()

    return 1


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "career.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # Access logs are noise against a tight shared ingestion cap.
        access_log=False,
    )
    return 0


def _pipeline() -> int:
    from .pipeline import run_pipeline

    result = run_pipeline()
    logging.getLogger("career").info("pipeline recorded %d cached listing(s)", len(result.listings))
    return 0


def _show() -> int:
    from . import store

    profile, _ = store.load_profile()
    jobs, _ = store.load_jobs()
    print(profile.to_json())
    print(jobs.to_json())
    return 0


def _seed(args: argparse.Namespace) -> int:
    from . import store
    from .seed import synthetic_jobs, synthetic_profile

    cfg = settings()
    if cfg.profile_container_url or cfg.jobs_container_url:
        print(
            "error: PROFILE_CONTAINER_URL/JOBS_CONTAINER_URL is set — seed data is for the "
            "local-file fallback only (see `make seed`). Unset them and retry.",
            file=sys.stderr,
        )
        return 1

    existing, _ = store.load_profile()
    if not args.force and (existing.roles or existing.certifications or existing.extra_skills):
        print(
            "error: the local profile already has data; pass --force to overwrite it.",
            file=sys.stderr,
        )
        return 1

    profile = synthetic_profile()
    jobs = synthetic_jobs(profile)
    store.save_profile(profile)
    store.save_jobs(jobs)
    logging.getLogger("career").info(
        "seeded: %d role(s), %d certification(s), %d job listing(s)",
        len(profile.roles),
        len(profile.certifications),
        len(jobs.listings),
    )
    return 0
