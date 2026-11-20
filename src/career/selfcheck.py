"""`career selfcheck`: prove a job's container could do a real run, and do nothing.

After every deploy, `make smoke` (workflows' smoke.sh) starts one run of each job
with its args swapped for `selfcheck`. That run gets everything a real one does
— the image, the managed identity, the env and the Key Vault references — and
checks what a real run needs before it does anything: the settings load, every
secret the pipeline and digest jobs read resolves, and both documents in
storage read; in the backup job, also its R2 keys and age keys, and that the
bucket lists. It fetches no listings, calls no LLM, sends no email and writes
nothing.

Exits 1 if any check fails, naming each failure but never a secret's value. A
failure fails the smoke test, which rolls the deploy back.

The required secrets are the ones the jobs read with `secret()`, which raises
on a missing value, so a run without one would fail anyway; an optional one
only has to resolve. Add a secret here when a job starts reading one.
"""

from __future__ import annotations

from appkit import selfcheck as kit

# backup.py's, which it reads with `secret()`, so they are required. Checked
# only in the job given a bucket, so a missing R2 key fails that job's
# selfcheck without it reading as a fault in the pipeline or the digest.
from appkit.backup import SECRETS as BACKUP_SECRETS

# Every secret the jobs read is optional: a source, the LLM or the digest is
# skipped without its key. Each still has to resolve without an error (Key
# Vault reachable, the identity allowed to read it).
OPTIONAL_SECRETS = ("REED-API-KEY", "DEEPSEEK-API-KEY", "RESEND-API-KEY", "DIGEST-TO")

__all__ = ["BACKUP_SECRETS", "OPTIONAL_SECRETS", "checks", "run"]


def checks() -> list[kit.Check]:
    from . import backup, integrity, store
    from .settings import optional_secret, settings

    return [
        ("settings", settings),
        *kit.optional_secret_checks(OPTIONAL_SECRETS, optional_secret),
        ("storage: profile", store.load_profile),
        ("storage: jobs", store.load_jobs),
        # The round trip only: will this release write back every stored value?
        # That is what a deploy can break. The rules are about the data, which a
        # deploy can't change: the store refuses new violations, and the backup
        # reports stored ones nightly. Gating here would let one old bad date
        # block every release, security fixes included.
        *kit.integrity_checks(
            store.PROFILE_BLOB,
            store.load_profile_raw,
            integrity.parse_profile,
            integrity.dump_profile,
        ),
        *kit.backup_checks(backup.JOB),
    ]


def run() -> int:
    return kit.run(checks())
