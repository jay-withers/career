# career.jaywithers.uk, on top of the platform-issued default hostname —
# same as this account's other apps. DNS (a CNAME for the hostname itself
# and a TXT record under asuid.career.jaywithers.uk for ownership
# verification) is managed by hand in Cloudflare, outside this repo; the two
# resources below are the Azure side of that same binding.

# Two-phase, not one — Azure's managed-certificate API refuses to issue a
# cert for a hostname that isn't already registered as a custom domain on
# some app in the environment (`RequireCustomHostnameInEnvironment`), so the
# domain had to exist (`Disabled`, no cert) before the cert could, on a first
# apply. Now that both exist, the reference below is what binds them.
resource "azurerm_container_app_custom_domain" "career" {
  name             = local.custom_domain
  container_app_id = azurerm_container_app.this.id

  certificate_binding_type                 = "SniEnabled"
  container_app_environment_certificate_id = azurerm_container_app_environment_managed_certificate.career.id
}

# Domain-validated (not HTTP-challenge-validated): the CNAME already in
# Cloudflare makes the domain resolve to this container app, so Azure can
# confirm control that way instead of needing a reachable HTTP challenge
# path of its own.
resource "azurerm_container_app_environment_managed_certificate" "career" {
  name                         = "cacert-${var.project_name}-${var.environment}"
  container_app_environment_id = data.azurerm_container_app_environment.platform.id
  subject_name                 = local.custom_domain
  domain_control_validation    = "CNAME"

  tags = local.tags
}
