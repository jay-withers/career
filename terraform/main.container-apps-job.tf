# The daily fetch/match/insights pipeline. A second workload alongside the
# app, on the same platform environment and reusing the same image — only
# `args` differs.
#
# **Why a job and not an in-process scheduler.** The app's `min_replicas = 0`
# (see main.container-apps.tf): nothing is running most of the day, so
# nothing could fire a scheduled task inside the app process itself. A
# Container App Job is the platform's answer to "run this on a schedule
# regardless of whether anything else is up" — same shape as repo-agent's
# weekly scan and gym-log's weekly insight/daily Garmin-sync jobs.
#
# A second naming module instance, unlike the app: a job's name must carry
# its workload to match the platform's job-failure alert convention
# (caj-<project>-<env>-<workload>, per repo-agent's naming_scan).
module "naming_pipeline" {
  # checkov:skip=CKV_TF_1: Terraform Registry module pinned by semver, as above.
  source  = "Azure/naming/azurerm"
  version = "~> 0.4"
  suffix  = [var.project_name, var.environment, "pipeline"]
}

resource "azurerm_container_app_job" "pipeline" {
  name                         = module.naming_pipeline.container_app_job.name
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = data.azurerm_container_app_environment.platform.id

  # Unlike the app, which rejects this argument: a job is not attached to a
  # revision the environment can place, so it must state its own region.
  location = data.azurerm_container_app_environment.platform.location

  # See main.container-apps.tf's identical argument on the app resource.
  workload_profile_name = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }

  # Fetching from three job-board APIs, matching against the profile and one
  # Anthropic call for the advancement guidance comfortably finishes in a
  # couple of minutes. Generous rather than tight, since a job that times out
  # retries at the caller's expense (another round of API calls), not for
  # free.
  replica_timeout_in_seconds = 600
  replica_retry_limit        = 1

  schedule_trigger_config {
    # 06:00 UTC — done well before the day starts, so a "refresh now" during
    # the day is the exception rather than the rule.
    cron_expression          = "0 6 * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "pipeline"
      image  = local.image
      cpu    = local.container_cpu
      memory = local.container_memory

      # Same image, different subcommand — see the app's own comment on why
      # `command` is never set.
      args = ["pipeline"]

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

  # Mirrors the app: `make deploy` rolls the app's image forward, and this
  # job should track the same released version rather than the one from its
  # own last `terraform apply`.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      template[0].container[0].env,
    ]
  }
}
