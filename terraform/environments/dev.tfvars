environment = "dev"

# Jay's Entra user: Key Vault Secrets Officer and blob access.
key_vault_administrator_object_ids = ["b168eef0-d213-406e-a7f9-7b9198d580da"]

# The variable's own default (v0.0.1) is the repo's very first tag, cut from
# the template baseline before src/ existed — cd-publish never built an image
# for it (nothing under src/Dockerfile/pyproject.toml/uv.lock to publish), so
# it 404s on GHCR. v0.1.0 is the first tag that actually has an image.
image_tag = "v0.1.0"
