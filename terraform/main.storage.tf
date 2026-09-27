# Where the career profile and the cached job listings live.
#
# Two small JSON documents, each read whole on each request and written whole
# when changed — the same shape as jay-withers/gym-log's training log, and for
# the same reason: there is no query to serve that a document store answers
# better than "read it, look at it in Python". At this scale (a handful of
# roles/certs and a few hundred cached listings) that stays comfortably small.
#
# PostgreSQL/SQLite-on-a-volume were both considered and rejected. Postgres
# bills whether or not anything uses it (market-agent's Flexible Server is the
# one thing in the estate that does, at ~£13/month), and a mounted volume
# needs the shared Consumption-only environment to support it and pins this
# app to a single replica for safe writes — which two independent JSON
# documents already get for free, with no new infrastructure shape to
# introduce into this account.
resource "azurerm_storage_account" "this" {
  # **`prevent_destroy` is set, same reasoning as gym-log's training-log
  # account.** `profile.json` is the product: career history and
  # certifications edited by hand through the app's own UI, seeded once from a
  # LinkedIn export that will not reproduce those edits if lost. `jobs.json`
  # sits in the same account for simplicity — it is fully regenerable by the
  # pipeline job, but the account-level guard costs nothing extra to keep.
  #
  # checkov:skip=CKV_AZURE_206: LRS on purpose. LRS is already eleven nines of
  #   durability within the region; the realistic risk to these documents is a
  #   bad write or an accidental delete, which versioning and the retention
  #   policies below cover and which geo-redundancy would not.
  # checkov:skip=CKV_AZURE_59: public network access stays enabled, for the
  #   same reason as the Key Vault — a scale-to-zero container app on a
  #   Consumption-only shared environment has neither a VNet to peer nor a
  #   static egress IP to allow.
  # checkov:skip=CKV_AZURE_33: no queues are used, so queue logging has
  #   nothing to log.
  # checkov:skip=CKV2_AZURE_1: platform-managed keys. A CMK needs a second Key
  #   Vault key, rotation and a managed identity grant on it, to protect a
  #   personal career profile and some cached job postings.
  # checkov:skip=CKV2_AZURE_32: no private endpoint, as above.
  # checkov:skip=CKV2_AZURE_33: no private endpoint, as above.
  # checkov:skip=CKV2_AZURE_47: public access as above.
  name                = module.naming.storage_account.name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location

  account_tier             = "Standard"
  account_kind             = "StorageV2"
  account_replication_type = "LRS"

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = true

  # **Entra ID only.** Turning off shared keys means no connection string and
  # no SAS exists to leak, and the managed identity below is the only way in.
  shared_access_key_enabled = false

  blob_properties {
    # Every save becomes a version, which is the undo this application does
    # not otherwise have: a role edited with the wrong dates, or a re-import
    # that goes wrong, is recoverable rather than argued with.
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = local.tags
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy
resource "azurerm_storage_container" "profile" {
  # No `prevent_destroy` of its own: the account above already blocks the
  # destroy, and the container delete retention policy covers the rest.
  #
  # checkov:skip=CKV2_AZURE_21: no blob read logging. It would land in the
  #   shared Log Analytics workspace, whose `daily_quota_gb = 0.15` is split
  #   across every tenant on the platform — spent on recording that a page
  #   load read one file.
  name                  = "profile"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy
resource "azurerm_storage_container" "jobs" {
  # checkov:skip=CKV2_AZURE_21: no blob read logging, as above.
  name                  = "jobs"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# The app reads and writes the profile through this. Scoped to the container
# rather than the account: the identity has no reason to reach any other
# container.
resource "azurerm_role_assignment" "identity_profile_contributor" {
  scope                = local.profile_container_scope
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
  # Stated explicitly: without it the provider looks the principal up in the
  # directory, which fails intermittently on an identity created moments ago.
  principal_type = "ServicePrincipal"
}

# The pipeline job (and the app's "refresh now" button) read and write the
# cached listings, market insights and advancement guidance through this.
resource "azurerm_role_assignment" "identity_jobs_contributor" {
  scope                = local.jobs_container_scope
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
  principal_type       = "ServicePrincipal"
}

# Whoever applies can read and edit either document by hand — which is what
# `make import`/`make show` do, running locally against the real blobs.
resource "azurerm_role_assignment" "deployer_profile_contributor" {
  for_each = toset(concat(
    [data.azurerm_client_config.current.object_id],
    var.key_vault_administrator_object_ids,
  ))

  scope                = local.profile_container_scope
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "deployer_jobs_contributor" {
  for_each = toset(concat(
    [data.azurerm_client_config.current.object_id],
    var.key_vault_administrator_object_ids,
  ))

  scope                = local.jobs_container_scope
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}
