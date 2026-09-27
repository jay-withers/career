config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "azurerm" {
  enabled = true
  version = "0.32.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

# This rule wants `lifecycle { prevent_destroy = true }` on stateful resources.
# The Key Vault here is a cheap, destroyable-on-demand resource holding only
# copied job-board/passcode secrets, not the thing worth protecting — that's
# the storage account (main.storage.tf), which already carries the guard.
# Excluding the specific type rather than disabling the rule keeps it armed
# for anything else stateful added later.
rule "azurerm_resources_missing_prevent_destroy" {
  enabled = true
  exclude = [
    "azurerm_key_vault",
  ]
}
