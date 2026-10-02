# career.jaywithers.uk, on top of the platform-issued default hostname —
# same as this account's other apps. DNS (a CNAME for the hostname itself
# and a TXT record under asuid.career.jaywithers.uk for ownership
# verification) is managed by hand in Cloudflare, outside this repo; the two
# resources below are the Azure side of that same binding.

# Two-phase, not one — Azure's managed-certificate API refuses to issue a
# cert for a hostname that isn't already registered as a custom domain on
# some app in the environment (`RequireCustomHostnameInEnvironment`), so the
# domain had to exist (`Disabled`, no cert) before the cert could, on a first
# apply.
#
# The binding itself isn't set here: `container_app_environment_certificate_id`
# only accepts an *uploaded* certificate's id (`.../certificates/...`) and
# rejects a managed one's (`.../managedCertificates/...`) at plan time, and
# the provider exposes the managed binding only as the read-only
# `container_app_environment_managed_certificate_id`. So the binding (made
# once, `SniEnabled` to cacert-career-dev) lives outside config, and both
# arguments are ignored — the provider's own documented pattern for managed
# certificates, which otherwise proposes unbinding the cert on every plan.
resource "azurerm_container_app_custom_domain" "career" {
  name             = local.custom_domain
  container_app_id = azurerm_container_app.this.id

  # Ordering only: the domain is bound to this certificate, so it shouldn't
  # outlive it.
  depends_on = [azurerm_container_app_environment_managed_certificate.career]

  lifecycle {
    ignore_changes = [certificate_binding_type, container_app_environment_certificate_id]
  }
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
