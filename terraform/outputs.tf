output "resource_group_name" {
  description = "This project's resource group."
  value       = data.azurerm_resource_group.this.name
}

# The whole point of the deployment: the URL opened in a browser. The custom
# domain, not `azurerm_container_app.this.ingress[0].fqdn` (the
# platform-issued default hostname, still live but no longer the one to
# bookmark) or `latest_revision_fqdn` (which changes with every revision).
output "app_url" {
  description = "The application's stable HTTPS URL. Bookmark this one; it survives deploys."
  value       = "https://${azurerm_container_app_custom_domain.career.name}"
}

output "container_app_name" {
  description = "Name of the container app, which `make deploy` passes to `az containerapp update`."
  value       = azurerm_container_app.this.name
}

output "container_app_job_name" {
  description = "Name of the daily pipeline job, which `make deploy` passes to `az containerapp job update`."
  value       = azurerm_container_app_job.pipeline.name
}

output "backup_job_name" {
  description = "Name of the nightly backup job, for `make deploy` and for starting a run by hand with `az containerapp job start`."
  value       = azurerm_container_app_job.backup.name
}

output "backup_bucket" {
  description = "The backup job's R2 bucket, which `make deploy` sets on it alongside the image."
  value       = var.backup_bucket
}

output "backup_r2_endpoint" {
  description = "The backup bucket's S3 endpoint, which `make deploy` sets on the backup job."
  value       = var.backup_r2_endpoint
}

output "backup_age_recipient" {
  description = "The owner's age public key, which `make deploy` sets on the backup job."
  value       = var.backup_age_recipient
}

output "digest_job_name" {
  description = "Name of the weekly digest job, which `make deploy` also passes to `az containerapp job update`."
  value       = azurerm_container_app_job.digest.name
}

output "key_vault_name" {
  description = "Key Vault name, for populating secrets with `az keyvault secret set`."
  value       = azurerm_key_vault.this.name
}

output "identity_client_id" {
  description = "Client ID of the workload identity, which the container receives as `AZURE_CLIENT_ID` and uses to reach Key Vault and both blob containers."
  value       = azurerm_user_assigned_identity.this.client_id
}

# What `make deploy` pushes onto the running revision, because `common_env`
# sits under `ignore_changes` and Terraform will therefore never update it
# itself.
output "profile_container_url" {
  description = "Blob container holding the career profile, for `make deploy` and for `make show` run locally."
  value       = "${azurerm_storage_account.this.primary_blob_endpoint}${azurerm_storage_container.profile.name}"
}

output "jobs_container_url" {
  description = "Blob container holding the cached job listings, market insights and advancement guidance."
  value       = "${azurerm_storage_account.this.primary_blob_endpoint}${azurerm_storage_container.jobs.name}"
}
