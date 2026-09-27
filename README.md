# career

A personal web app: career profile storage (roles, experience,
certifications — seeded from a LinkedIn data export), job-opportunity
aggregation from a handful of job-board APIs, and market/advancement
insights derived from what that aggregation collects.

Runs as a single-user tool on `jay-withers/azure-container-apps`' shared
Container Apps environment, the same shape as `jay-withers/gym-log` and
`jay-withers/finances` — see `terraform/README.md` for the infrastructure
and `CLAUDE.md` for the full design reasoning.

## What it does

- **Profile**: roles, certifications and the skills derived from them,
  edited through the app's own UI. Seed it once from LinkedIn's own "Get a
  copy of your data" export (Settings & Privacy → Data privacy) at
  `/profile/import` — the export itself is parsed in memory and never
  retained, only the derived rows are saved.
- **Jobs**: a daily pipeline (`career pipeline`, run as a scheduled
  Container Apps Job) fetches listings from Adzuna, RemoteOK and Arbeitnow,
  scores each one against the stored profile, and caches the result for
  review at `/jobs`. A "refresh now" button runs the same pipeline
  on demand.
- **Insights**: `/insights` shows which of the profile's own skills are
  most in-demand across the cached listings, the most common titles seen,
  and — when a DeepSeek API key is configured — an LLM-synthesized
  advancement guidance: skill gaps and plausible next roles.

## Getting started

Open the repository in the dev container (VS Code: **Reopen in Container**,
or GitHub Codespaces), which runs `make install` on creation to wire up the
pre-commit hooks and Python dependencies. Outside a dev container:

```bash
make install
```

Then, with no Azure involved at all:

```bash
make run              # serve on :8000 against a local profile/jobs file
make pipeline-local    # run the fetch/match/insights pipeline locally
```

`make run` reads `APP_PASSCODE` from the environment (default `local` if
unset) and falls back to `.career-profile.json`/`.career-jobs.json` in the
working directory when `PROFILE_CONTAINER_URL`/`JOBS_CONTAINER_URL` aren't
set — see `.env.example`.

A fresh checkout's local profile and job cache are both empty. Run
`make seed` to fill them with an invented Senior Platform Engineer profile
and a matching set of scored job listings, so the review queue, insights
and advancement pages all have something to show. It refuses to touch a
local profile that already has data (pass `make seed FORCE=1` to overwrite
it) and refuses outright if `PROFILE_CONTAINER_URL`/`JOBS_CONTAINER_URL` are
set, so it can never overwrite the real deployed data.

## Commands

Run `make` (or `make help`) to list every target. The ones worth knowing:

```bash
make test        # run the test suite (pytest)
make lint         # run every pre-commit hook against every file
make run          # serve locally against local files
make seed         # write synthetic profile/job data to the local files
make pipeline-local  # run the pipeline locally
make import FILE=path/to/export.zip   # import a LinkedIn export, against the real profile
make show         # print the deployed profile and job cache as JSON
make build        # build the container image (linux/amd64)
make deploy IMAGE_TAG=vX.Y.Z  # roll a published tag onto the app and the pipeline job
```

`terraform/README.md` has the Terraform-side commands (`init`/`fmt`/
`validate`/`plan`/`apply`) and the `az keyvault secret set` calls
(`make secrets`) needed before the deployed app or pipeline job can start.

## Structure

```text
src/career/
  settings.py     # config + secret resolution (env → .env → Key Vault)
  model.py        # Profile/Role/Certification and JobsDocument/JobListing — frozen dataclasses, hand-written JSON
  store.py        # read-whole/write-whole blob (or local file) storage for both documents, with ETag concurrency
  importer.py     # parses a LinkedIn data export zip into Role/Certification/skill rows
  matching.py     # rule-based relevance scoring of a listing against the profile
  insights.py     # market insights: skill/title frequency across cached listings
  advancement.py  # the one LLM call in the app: career-advancement gap analysis
  pipeline.py     # orchestrates fetch → match → insights → advancement → save
  sources/        # one adapter per job board (adzuna, remoteok, arbeitnow)
  api/            # FastAPI app: passcode gate, routes, server-rendered Jinja2 templates
  cli.py          # career serve|pipeline|import|show
tests/            # pytest, mirroring the modules above
terraform/        # this project's own infrastructure — see terraform/README.md
Dockerfile
Makefile
```
