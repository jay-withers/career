# career

A personal web app: career profile storage (roles, experience,
certifications), job-opportunity
aggregation from a handful of job-board APIs, and market/advancement
insights derived from what that aggregation collects.

Runs as a single-user tool on `jay-withers/azure-container-apps`' shared
Container Apps environment, the same shape as `jay-withers/gym-log` and
`jay-withers/finances` — see `terraform/README.md` for the infrastructure
and `CLAUDE.md` for the full design reasoning.

## What it does

- **Profile**: roles, certifications and the skills derived from them,
  edited through the app's own UI, plus job preferences (work mode, salary,
  how far from home) that the matching respects.
- **Jobs**: a daily pipeline (`career pipeline`, run as a scheduled
  Container Apps Job) fetches listings from Reed,
  scores each one against the stored profile, and caches the result for
  review at `/jobs`. A "refresh now" button runs the same pipeline
  on demand.
- **Insights**: `/insights` shows which of the profile's own skills are
  most in-demand across the cached listings, the most common titles seen,
  and — when a DeepSeek API key is configured — an LLM-synthesized
  advancement guidance: skill gaps and plausible next roles.
- **Weekly digest**: every Friday at 19:00 UTC, a second job
  (`career digest`) emails the week's new matches through Resend. It reads
  the cache the pipeline wrote and fetches nothing. Without `RESEND-API-KEY`
  and `DIGEST-TO` in Key Vault it skips the send.

It's served at `career.jaywithers.uk`, an Azure-managed certificate on a
custom domain whose DNS records live in
[jay-withers/cloudflare](https://github.com/jay-withers/cloudflare).

## Getting started

Once per machine, set up the tools with
[jay-withers/toolchain](https://github.com/jay-withers/toolchain)
(`bash src/setup.sh`), which installs [mise](https://mise.jdx.dev). Then, in
this repo:

```bash
mise trust && make install   # make install runs `mise install` first
```

`mise.toml` pins every tool this repo's hooks, build and CI use; CI installs
the same versions (jay-withers/workflows v1.26.1+). Add a tool there rather
than installing it by hand.

`make install` also syncs the Python dependencies with uv.

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
make typecheck   # mypy; CI runs it too
make lint         # run every pre-commit hook against every file
make run          # serve locally against local files
make seed         # write synthetic profile/job data to the local files
make pipeline-local  # run the pipeline locally
make digest-preview  # render the weekly email from local files into .digest-preview/, sending nothing
make show         # print the deployed profile and job cache as JSON
make pipeline     # run the pipeline against the real blobs
make url          # the deployed app's URL
make logs         # tail the deployed app's logs
make build        # build the container image (linux/amd64)
make push         # push it to ghcr.io (needs write:packages)
make deploy IMAGE_TAG=vX.Y.Z  # roll a published tag onto the app, the pipeline job and the digest job
```

`terraform/README.md` has the Terraform-side commands (`init`/`fmt`/
`validate`/`plan`/`apply`) and the `az keyvault secret set` calls
(`make secrets`) needed before the deployed app or pipeline job can start.

**Releases deploy themselves.** When a merge publishes a new image,
`cd-publish`'s `deploy` job runs this same `make deploy IMAGE_TAG=<release>`
against dev, through the shared `container-apps-deploy.yml` (OIDC in the `dev`
GitHub environment). To redeploy an existing tag — after a failed deploy, or an
apply that recreated a workload — run `cd-publish` from the Actions tab with
that tag. Running `make deploy` by hand is for anything else, such as a
rollback.

**Every deploy is smoke-tested, and a failed one rolls back.** Before deploying,
the workflow records `make deployed-tag` (the tag on the app now). After it,
`make smoke` (`scripts/smoke.sh`) checks that the app and every job are configured with
the new tag, that the app's `/healthz` reports it as `version` on its default
FQDN (allowing five minutes for a cold start), and that `/readyz` answers 200.
It then starts one run of each job with its args swapped for `career selfcheck`,
which checks the settings, secrets and storage a real run needs and does
nothing else, and waits for each to succeed.
If the deploy or the smoke test fails, the workflow redeploys the recorded tag,
smoke-tests that, and fails the run, so a `deploy-failed` issue says whether
dev is back on the old version. Rolling back moves the image only: a release
must not change stored data in a way the previous version can't read.

## Backups

The profile is one blob in one LRS storage account. Versioning, soft delete and
`prevent_destroy` cover a bad write or a slip of the hand, but not losing the
subscription. So the **backup job** (`career backup`, 03:00 UTC daily) copies
`profile.json` to the cloudflare repo's R2 bucket `jw-app-backups`, encrypted
with [age](https://age-encryption.org). It works the same way as gym-log's and
finances':

- `daily/career/<UTC timestamp>/profile.json.age`, kept 30 days.
- `monthly/career/<yyyy-mm>/profile.json.age`, written by the first run in the
  month whose daily copy verifies, kept a year.

Only the profile: the job cache (`jobs.json`) is rebuilt from the job boards
by every pipeline run. Nothing is overwritten: a rerun adds a copy beside the
earlier ones.

Each copy is encrypted to two keys. One is **the owner's**, whose public half
is `backup_age_recipient` in `terraform/environments/dev.tfvars` (the same key
as the other apps') and whose private half is kept offline. The other is a
**drill key** in Key Vault (`BACKUP-AGE-DRILL-KEY`). After every upload the job
downloads the copy, decrypts it with the drill key, checks it matches byte for
byte and parses it as a `Profile`. Any failure fails the job, and the
platform's job-failure alert fires.

**Setup (once):** put the R2 token's two halves (an Account API token with
**Object Read & Write** on `jw-app-backups` only; the other apps' works) in Key
Vault as `R2-ACCESS-KEY-ID` and `R2-SECRET-ACCESS-KEY`, and generate the drill
key straight into Key Vault. `make secrets` prints all three commands. Do it
**before** a release with the backup job deploys: the job's selfcheck checks
them, so a missing one fails the smoke test and rolls the release back.

**Restoring.** Download a copy from the R2 dashboard. Put the private key in a
file outside any repository (`cat > ~/backup.key`, paste, Ctrl+D; never `echo`
it, where shell history keeps it), then:

```bash
mise exec age@latest -- age -d -i ~/backup.key -o profile.json profile.json.age
LOCAL_PROFILE_PATH=profile.json uv run career show | head -1
rm ~/backup.key
```

Put it back with `az storage blob upload --auth-mode login --overwrite` into
the `profile` container (`make show` reads it), or into a new storage account
after a rebuild.

## CI/CD

Every workflow calls a shared one in
[jay-withers/workflows](https://github.com/jay-withers/workflows), pinned by
SHA.

- **ci-pre-commit**, **ci-python** (pytest, mypy and diff coverage),
  **ci-container-build** (build plus Trivy) and **ci-terraform** (validate,
  then a real plan of dev commented on the PR) on pull requests.
  **ci-codeql** scans the workflows.
- **cd-tag** → **cd-publish**: a release on every merge; when app files
  changed, the image is published to
  `ghcr.io/jay-withers/career/career` and deployed as above.
- **cd-terraform**: plans dev on merge and opens a `terraform-pending` issue;
  **Actions → cd-terraform → Run workflow** applies it.
- **schedule-drift**: a nightly plan of dev, recorded in the platform's
  `OpsEvents_CL` table. **manual-terraform-unlock** releases a stuck state
  lock.

## Structure

```text
src/career/
  settings.py     # config + secret resolution (env → .env → Key Vault)
  model.py        # Profile/Role/Certification and JobsDocument/JobListing — frozen dataclasses, hand-written JSON
  store.py        # read-whole/write-whole blob (or local file) storage for both documents, with ETag concurrency
  matching.py     # rule-based relevance scoring of a listing against the profile
  insights.py     # market insights: skill/title frequency across cached listings
  advancement.py  # the one LLM call in the app: career-advancement gap analysis
  pipeline.py     # orchestrates fetch → match → insights → advancement → save
  digest.py       # the weekly email of new matches, through Resend
  distance.py     # straight-line distance from home, from a small UK gazetteer
  selfcheck.py    # the post-deploy check: settings, secrets and storage
  telemetry.py    # Application Insights, configured at start-up and flushed before exit
  sources/        # one adapter per job board (currently just reed)
  api/            # FastAPI app: passcode gate, routes, server-rendered Jinja2 templates
  cli.py          # career serve|pipeline|digest|show|seed|selfcheck
tests/            # pytest, mirroring the modules above
terraform/        # this project's own infrastructure — see terraform/README.md
scripts/smoke.sh  # make smoke (shared verbatim with the other apps)
Dockerfile
Makefile
```
