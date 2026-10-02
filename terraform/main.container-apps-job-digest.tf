# The weekly digest email — a third workload on the same image, alongside the
# app and the daily pipeline (main.container-apps-job.tf), differing only in
# `args`. See that file for why a scheduled job rather than an in-process
# scheduler.
#
# It reads the job cache the 06:00 pipeline wrote that morning and sends one
# email through Resend (see src/career/digest.py), so it's quick and touches
# nothing but the jobs/profile blobs and Key Vault.

# Its own naming instance, for the same job-failure alert convention as the
# pipeline's (caj-<project>-<env>-<workload>).
module "naming_digest" {
  # checkov:skip=CKV_TF_1: Terraform Registry module pinned by semver, as above.
  source  = "Azure/naming/azurerm"
  version = "~> 0.4"
  suffix  = [var.project_name, var.environment, "digest"]
}

resource "azurerm_container_app_job" "digest" {
  name                         = module.naming_digest.container_app_job.name
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = data.azurerm_container_app_environment.platform.id

  # See main.container-apps-job.tf: a job must state its own region.
  location = data.azurerm_container_app_environment.platform.location

  workload_profile_name = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }

  # Two blob reads, two secrets and one HTTP call. One retry is safe: the
  # request carries a per-week idempotency key, so Resend answers a repeat
  # with the email it already sent rather than sending another.
  replica_timeout_in_seconds = 300
  replica_retry_limit        = 1

  schedule_trigger_config {
    # Fridays, 19:00 UTC — 20:00 in British Summer Time, 19:00 in winter.
    # Container Apps cron has no time zone, so it can't track the clocks
    # changing; early evening either way.
    cron_expression          = "0 19 * * 5"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "digest"
      image  = local.image
      cpu    = local.container_cpu
      memory = local.container_memory

      # Same image, different subcommand — see the app's comment on why
      # `command` is never set.
      args = ["digest"]

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  tags = local.tags

  # Mirrors the app and the pipeline: `make deploy` rolls the image forward.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      template[0].container[0].env,
    ]
  }
}
