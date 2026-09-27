locals {
  # Assembled by hand: `azurerm_storage_container` exports no Resource Manager
  # id, and its `id` is the data-plane URL, which a role assignment rejects.
  profile_container_scope = "${azurerm_storage_account.this.id}/blobServices/default/containers/${azurerm_storage_container.profile.name}"
  jobs_container_scope    = "${azurerm_storage_account.this.id}/blobServices/default/containers/${azurerm_storage_container.jobs.name}"

  image = "${var.image_registry}/career:${var.image_tag}"

  # uvicorn binds this, the Dockerfile EXPOSEs it, and both probes below check it.
  target_port = 8000

  # The smallest combination Container Apps accepts; memory must be 2 GiB per
  # vCPU. This renders a handful of Jinja templates and runs the daily
  # fetch/match/insights pipeline against a few hundred cached listings — it is
  # bounded by the cold start, not by CPU.
  container_cpu    = 0.25
  container_memory = "0.5Gi"

  # Everything the container needs that is not a secret. Secrets (the
  # passcode, job-board API keys, the DeepSeek API key) are resolved at
  # runtime from Key Vault by settings.py, not injected here — an env var is
  # visible in `az containerapp show` output and in state.
  common_env = {
    AZURE_CLIENT_ID                       = azurerm_user_assigned_identity.this.client_id
    KEY_VAULT_URI                         = azurerm_key_vault.this.vault_uri
    APPLICATIONINSIGHTS_CONNECTION_STRING = data.azurerm_application_insights.platform.connection_string
    ENVIRONMENT                           = var.environment
    # Recorded so a trace names the build that produced it.
    IMAGE_TAG = var.image_tag
    # Where the career profile and the cached job listings are read and
    # written. Not secrets — they are URLs, and reaching them still needs the
    # managed identity's RBAC grant on each container.
    PROFILE_CONTAINER_URL = "${azurerm_storage_account.this.primary_blob_endpoint}${azurerm_storage_container.profile.name}"
    JOBS_CONTAINER_URL    = "${azurerm_storage_account.this.primary_blob_endpoint}${azurerm_storage_container.jobs.name}"
  }
}
