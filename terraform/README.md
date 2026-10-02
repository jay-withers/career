# terraform

This project's own infrastructure: a resource group, Key Vault, storage
account (holding the career profile and the cached job listings as two JSON
blobs) and identity, plus a `azurerm_container_app` (the web app) and a
`azurerm_container_app_job` (the daily fetch/match/insights pipeline). The
shared Container Apps environment it runs on lives in
`jay-withers/azure-container-apps` and is resolved by name in `data.tf`, not
by reading that repository's state.

Same shape as `jay-withers/gym-log`/`jay-withers/finances`: a tenant of the
shared platform rather than a root module of its own, with only `dev`
deployed (`terraform/environments/dev.tfvars`) — see `data.tf`'s comment on
why a plan against an environment the platform hasn't been applied to fails
at plan time, which is also why there's no dev/stg/prd matrix here.

## Commands

```bash
make init      # terraform init, without configuring the state backend
make fmt       # terraform fmt -recursive
make validate  # terraform init + validate (no Azure credentials needed)
make plan      # terraform init + plan
make apply     # terraform init + apply
```

`make plan`/`apply` need Azure credentials (`az login`, `ARM_SUBSCRIPTION_ID`
or equivalent) with rights on the subscription — this resolves the shared
platform environment via a data source, so even a plan needs real
credentials against an already-applied platform, unlike `github-repos`'
GitHub-only side.

## Secrets

Terraform creates the Key Vault but deliberately no
`azurerm_key_vault_secret` — no secret value belongs in source or in state.
Run `make secrets` for the exact `az keyvault secret set` commands once the
vault exists:

- `APP-PASSCODE` — required; gates the deployed app (see
  `src/career/api/deps.py`)
- `REED-API-KEY` — optional but recommended, the main UK source; free from
  reed.co.uk/developers (see `src/career/sources/reed.py`)
- `DEEPSEEK-API-KEY` — optional; without it the advancement-guidance step
  is skipped (see `src/career/advancement.py`)
- `RESEND-API-KEY` and `DIGEST-TO` — optional; the Resend API key and the
  address the Friday digest goes to (see `src/career/digest.py`). Without
  both the digest job runs and sends nothing. The address is a secret only
  to keep it out of this public repository.

### Sending domain

The digest is sent from `digest@career.jaywithers.uk`, so
`career.jaywithers.uk` must be a verified domain in Resend. Add it in the
Resend dashboard, then create the DNS records it lists (a DKIM TXT record,
and the SPF MX/TXT pair on `send.career.jaywithers.uk`) by hand in
Cloudflare — the same place as the app's own CNAME and `asuid` TXT records
(see `main.container-apps-domain.tf`). None of them clash with the app's
CNAME on `career.jaywithers.uk` itself: they're all on names under it.

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.6 |
| <a name="requirement_azurerm"></a> [azurerm](#requirement\_azurerm) | ~> 4.0 |
| <a name="requirement_random"></a> [random](#requirement\_random) | >= 3.3.2 |

## Providers

| Name | Version |
| ---- | ------- |
| <a name="provider_azurerm"></a> [azurerm](#provider\_azurerm) | 4.81.0 |

## Modules

| Name | Source | Version |
| ---- | ------ | ------- |
| <a name="module_naming"></a> [naming](#module\_naming) | Azure/naming/azurerm | ~> 0.4 |
| <a name="module_naming_digest"></a> [naming\_digest](#module\_naming\_digest) | Azure/naming/azurerm | ~> 0.4 |
| <a name="module_naming_pipeline"></a> [naming\_pipeline](#module\_naming\_pipeline) | Azure/naming/azurerm | ~> 0.4 |

## Resources

| Name | Type |
| ---- | ---- |
| [azurerm_container_app.this](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app) | resource |
| [azurerm_container_app_custom_domain.career](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app_custom_domain) | resource |
| [azurerm_container_app_environment_managed_certificate.career](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app_environment_managed_certificate) | resource |
| [azurerm_container_app_job.digest](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app_job) | resource |
| [azurerm_container_app_job.pipeline](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/container_app_job) | resource |
| [azurerm_key_vault.this](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/key_vault) | resource |
| [azurerm_resource_group.this](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/resource_group) | resource |
| [azurerm_role_assignment.deployer_jobs_contributor](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/role_assignment) | resource |
| [azurerm_role_assignment.deployer_profile_contributor](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/role_assignment) | resource |
| [azurerm_role_assignment.deployer_secrets_officer](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/role_assignment) | resource |
| [azurerm_role_assignment.identity_jobs_contributor](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/role_assignment) | resource |
| [azurerm_role_assignment.identity_profile_contributor](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/role_assignment) | resource |
| [azurerm_role_assignment.identity_secrets_user](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/role_assignment) | resource |
| [azurerm_storage_account.this](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/storage_account) | resource |
| [azurerm_storage_container.jobs](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/storage_container) | resource |
| [azurerm_storage_container.profile](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/storage_container) | resource |
| [azurerm_user_assigned_identity.this](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/user_assigned_identity) | resource |
| [azurerm_application_insights.platform](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/data-sources/application_insights) | data source |
| [azurerm_client_config.current](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/data-sources/client_config) | data source |
| [azurerm_container_app_environment.platform](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/data-sources/container_app_environment) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| <a name="input_environment"></a> [environment](#input\_environment) | Deployment environment. Drives resource naming, and selects which shared platform environment this project deploys onto. | `string` | n/a | yes |
| <a name="input_image_registry"></a> [image\_registry](#input\_image\_registry) | Registry and repository prefix the image is pulled from. A public package on ghcr.io deliberately: a private one would need a `registry` block and a Key Vault-backed pull secret on the app, and there is no Azure Container Registry because ACR Basic is a flat monthly charge with no consumption tier. | `string` | `"ghcr.io/jay-withers/career"` | no |
| <a name="input_image_tag"></a> [image\_tag](#input\_image\_tag) | Image tag seeding the app's **first** revision only. Every deploy after that is `make deploy IMAGE_TAG=vX.Y.Z`, because the container's image and env sit under `ignore_changes` — so a plan against an existing deployment reports no change here even when the running image has moved on. Don't read a stale-looking default as the deployed version. | `string` | `"v0.0.1"` | no |
| <a name="input_key_vault_administrator_object_ids"></a> [key\_vault\_administrator\_object\_ids](#input\_key\_vault\_administrator\_object\_ids) | Extra Entra object IDs granted Key Vault Secrets Officer and Storage Blob Data Contributor. Whoever runs `terraform apply` is always included, so this is only for a second person or a second machine. | `list(string)` | `[]` | no |
| <a name="input_platform_app_insights_name"></a> [platform\_app\_insights\_name](#input\_platform\_app\_insights\_name) | Name of the shared Application Insights instance the app reports telemetry to. | `string` | `"appi-platform-dev"` | no |
| <a name="input_platform_environment_name"></a> [platform\_environment\_name](#input\_platform\_environment\_name) | Name of the shared Container Apps environment this app runs on. | `string` | `"cae-platform-dev"` | no |
| <a name="input_platform_resource_group_name"></a> [platform\_resource\_group\_name](#input\_platform\_resource\_group\_name) | Resource group holding the shared Container Apps environment. | `string` | `"rg-platform-dev"` | no |
| <a name="input_project_name"></a> [project\_name](#input\_project\_name) | Short name for this project, used by the naming module for every resource. | `string` | `"career"` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | Tags merged over the defaults in locals.tf. | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| <a name="output_app_url"></a> [app\_url](#output\_app\_url) | The application's stable HTTPS URL. Bookmark this one; it survives deploys. |
| <a name="output_container_app_job_name"></a> [container\_app\_job\_name](#output\_container\_app\_job\_name) | Name of the daily pipeline job, which `make deploy` passes to `az containerapp job update`. |
| <a name="output_container_app_name"></a> [container\_app\_name](#output\_container\_app\_name) | Name of the container app, which `make deploy` passes to `az containerapp update`. |
| <a name="output_digest_job_name"></a> [digest\_job\_name](#output\_digest\_job\_name) | Name of the weekly digest job, which `make deploy` also passes to `az containerapp job update`. |
| <a name="output_identity_client_id"></a> [identity\_client\_id](#output\_identity\_client\_id) | Client ID of the workload identity, which the container receives as `AZURE_CLIENT_ID` and uses to reach Key Vault and both blob containers. |
| <a name="output_jobs_container_url"></a> [jobs\_container\_url](#output\_jobs\_container\_url) | Blob container holding the cached job listings, market insights and advancement guidance. |
| <a name="output_key_vault_name"></a> [key\_vault\_name](#output\_key\_vault\_name) | Key Vault name, for populating secrets with `az keyvault secret set`. |
| <a name="output_profile_container_url"></a> [profile\_container\_url](#output\_profile\_container\_url) | Blob container holding the career profile, for `make deploy` and for `make show` run locally. |
| <a name="output_resource_group_name"></a> [resource\_group\_name](#output\_resource\_group\_name) | This project's resource group. |
<!-- END_TF_DOCS -->
