# Its own naming instance, for the job-failure alert convention
# (caj-<project>-<env>-<workload>). `caj-career-dev-backup` is 21 characters.
module "naming_backup" {
  # checkov:skip=CKV_TF_1: Terraform Registry module pinned by semver, as above.
  source  = "Azure/naming/azurerm"
  version = "~> 0.4"
  suffix  = [var.project_name, var.environment, "backup"]
}

# The nightly off-Azure backup (`career backup`, src/career/backup.py): an
# age-encrypted copy of the profile in the cloudflare repo's R2 bucket,
# downloaded again and decrypted with the drill key on every run to prove it
# restores. Adapted from finances' main.container-apps-job.backup.tf. Only the
# profile: the job cache is rebuilt by every pipeline run (see backup.py).
#
# A job inside this app rather than a GitHub workflow because this identity
# already reads the profile: a workflow would need a new grant on it for the
# pipeline identity. Running here also puts the
# job under the platform's job-failure alert and observability's heartbeat
# check (both learn jobs by name) with nothing added there.
resource "azurerm_container_app_job" "backup" {
  name                         = module.naming_backup.container_app_job.name
  container_app_environment_id = data.azurerm_container_app_environment.platform.id
  resource_group_name          = data.azurerm_resource_group.this.name

  # See main.container-apps-job.tf: a job must state its own region.
  location              = data.azurerm_container_app_environment.platform.location
  workload_profile_name = "Consumption"

  # One small profile, two uploads and two downloads. Five minutes is mostly
  # the cold start; the retry covers a transient R2 or Key Vault error, and a
  # second copy under a new timestamped key is harmless.
  replica_timeout_in_seconds = 300
  replica_retry_limit        = 1

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }

  schedule_trigger_config {
    # 03:00 UTC: after the day's edits, and after gym-log's (02:30) and
    # finances' (02:45) so the three don't cold-start together.
    cron_expression          = "0 3 * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "backup"
      image  = local.image
      cpu    = local.container_cpu
      memory = local.container_memory

      # No `command`: see the note on azurerm_container_app.this.
      args = ["backup"]

      dynamic "env" {
        for_each = local.backup_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  tags = local.tags

  # As the other jobs: `make deploy` owns the image and the env.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      template[0].container[0].env,
    ]
  }
}
