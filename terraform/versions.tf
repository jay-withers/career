terraform {
  required_version = ">= 1.6"

  # Partial: per-environment values live in backends/<env>.hcl.
  #   terraform init -backend-config=backends/dev.hcl
  # Anything not touching state must init with -backend=false, or this prompts.
  backend "azurerm" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
    # Transitive dependency of module.naming (Azure/naming/azurerm), declared
    # here explicitly so the module's full provider footprint is visible.
    random = {
      source  = "hashicorp/random"
      version = ">= 3.3.2"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }

    key_vault {
      # Let destroy actually remove the vault rather than leaving a
      # soft-deleted one holding the name.
      purge_soft_delete_on_destroy = true
    }
  }

  use_oidc = true

  # The storage account below disables shared-key auth
  # (`shared_access_key_enabled = false`), Entra-ID-only. Without this, the
  # provider still falls back to account-key auth to read ancillary
  # properties (e.g. queue properties) even when only blob is used, and that
  # fallback is what's rejected with `KeyBasedAuthenticationNotPermitted`.
  storage_use_azuread = true
}
