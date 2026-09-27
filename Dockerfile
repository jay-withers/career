# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

# Container Apps runs linux/amd64 only. A native build on an arm64 dev host
# produces an image that crash-loops with an exec format error and no other
# clue, so every build for deployment must pass --platform linux/amd64 — see
# the Makefile's `build` target.

# Builder and runtime both derive from `base`, and that is load-bearing
# rather than tidy: the runtime stage copies the whole virtualenv, and a venv
# is bound to the exact minor version that created it. One FROM line means
# the two stages cannot drift onto different interpreters — see
# jay-withers/gym-log's identical comment for the outage that taught this.
FROM python:3.14-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56 AS base


FROM base AS builder

# uv is copied in rather than supplying the base image, which is exactly what
# lets the builder share the runtime's interpreter. UV_PYTHON_DOWNLOADS=never
# then stops uv fetching a different one of its own.
COPY --from=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies before source, so editing a module does not re-resolve the
# whole environment. --frozen fails rather than silently updating uv.lock,
# which is what makes the image reproducible.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --no-editable

COPY src ./src
# --no-editable matters: without it uv installs the project as a link back to
# /app/src, and the runtime stage copies only the virtualenv — leaving a .pth
# pointing at a directory that does not exist there.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM base AS runtime

# This label is what connects the pushed package to this repository, and
# that connection is what gives a workflow's GITHUB_TOKEN write access to it.
LABEL org.opencontainers.image.source="https://github.com/jay-withers/career"

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Non-root, and no shell: nothing in here needs to log in. The uid is numeric
# and USER names the number, not the name.
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin career

WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv

USER 10001

EXPOSE 8000

# /healthz rather than /readyz deliberately: this decides whether to restart
# the container, and restarting it does not fix unreachable storage.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# **This ENTRYPOINT is the single source of truth for the executable's
# name.** Terraform sets no `command` on either the app or the pipeline job —
# only `args` — so renaming the console script is one atomic change here.
ENTRYPOINT ["career"]
CMD ["serve"]
