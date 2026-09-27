# The web application.
#
# Runs on the shared platform environment (see data.tf) but lives in this
# project's own resource group. That is allowed across resource groups but not
# across regions, which is why the resource group takes its location from the
# environment rather than from a variable of its own.
resource "azurerm_container_app" "this" {
  name                         = module.naming.container_app.name
  container_app_environment_id = data.azurerm_container_app_environment.platform.id
  resource_group_name          = azurerm_resource_group.this.name

  # No `location` argument: a container app inherits its environment's region
  # and the provider rejects the argument outright. Jobs are the exception
  # that must state it — see main.container-apps-job.tf.

  # Single, not Multiple. There is one user and one URL; weighted traffic
  # across revisions would mean a request answered by whichever revision
  # happened to be warm.
  revision_mode = "Single"

  # The shared environment has no other workload profile (Consumption-only,
  # the same reason the storage account's checkov skips give for no
  # VNet/private endpoint). Stated explicitly rather than left to the provider
  # default: the API already reports this back, and leaving it unset in
  # config made every plan propose clearing it.
  workload_profile_name = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }

  ingress {
    # Reachable from the internet, which is the point — this is checked from a
    # phone as easily as a laptop. The passcode gate in api/deps.py is what
    # stands in front of it, and it defaults on.
    external_enabled = true
    target_port      = local.target_port
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Scale to zero: a personal, single-user tool opened a few times a day has
    # no reason to bill for a standing replica.
    min_replicas = 0
    # One. Both blob documents use an ETag precondition (see store.py), but
    # there is still only one browser and no benefit to a second replica.
    max_replicas = 1

    container {
      name   = "career"
      image  = local.image
      cpu    = local.container_cpu
      memory = local.container_memory

      # No `command` argument, deliberately — the image's ENTRYPOINT already
      # names the console script. See gym-log's main.container-apps.tf for the
      # outage that taught this; the same reasoning applies verbatim here.
      args = ["serve"]

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Liveness must not depend on storage — a blob blip would otherwise
      # restart every replica and turn a brief outage into a crash loop.
      # /healthz answers from memory; /readyz is the one that reads.
      liveness_probe {
        transport               = "HTTP"
        port                    = local.target_port
        path                    = "/healthz"
        initial_delay           = 5
        interval_seconds        = 30
        timeout                 = 5
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = local.target_port
        path                    = "/readyz"
        interval_seconds        = 10
        timeout                 = 5
        failure_count_threshold = 3
        success_count_threshold = 1
      }
    }
  }

  tags = local.tags

  # `make deploy` (az cli) owns the running image and env after the first
  # revision, so that a deploy needs no state lock, no plan of unrelated
  # drift, and no risk of a stale local tfvars rolling the image backwards.
  # See gym-log's identical block for the full reasoning, including why
  # `command` is absent from this list — because it is absent from the
  # resource, which is the point.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      template[0].container[0].env,
    ]
  }
}
