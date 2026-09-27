# One identity for this project, used by the app and the pipeline job to read
# their own Key Vault and the profile/jobs blobs.
#
# Per-project rather than one shared across the platform: identities are free,
# and this one can read the passcode guarding a publicly reachable app, the
# job-board and DeepSeek API keys, and read-write the career profile and the
# cached job listings. A platform-wide identity would make all of that
# reachable from any future tenant's image.
resource "azurerm_user_assigned_identity" "this" {
  name                = module.naming.user_assigned_identity.name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}
