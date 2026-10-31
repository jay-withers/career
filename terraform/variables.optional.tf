variable "project_name" {
  description = "Short name for this project, used by the naming module for every resource."
  type        = string
  default     = "career"

  validation {
    # Lowercase only (container apps reject uppercase), and short enough that
    # `ca-<project>-<env>` fits the 32 characters container apps allow.
    condition     = can(regex("^[a-z][a-z0-9]{1,14}$", var.project_name))
    error_message = "project_name must be 2-15 lowercase alphanumerics starting with a letter."
  }
}

variable "tags" {
  description = "Tags merged over the defaults in locals.tf."
  type        = map(string)
  default     = {}
}

# --- the shared platform ------------------------------------------------------
#
# Resolved by name rather than from the platform's Terraform state. These
# defaults match jay-withers/azure-container-apps at its own defaults; run
# `make outputs` there to confirm.

variable "platform_resource_group_name" {
  description = "Resource group holding the shared Container Apps environment."
  type        = string
  default     = "rg-platform-dev"
}

variable "platform_environment_name" {
  description = "Name of the shared Container Apps environment this app runs on."
  type        = string
  default     = "cae-platform-dev"
}

variable "platform_app_insights_name" {
  description = "Name of the shared Application Insights instance the app reports telemetry to."
  type        = string
  default     = "appi-platform-dev"
}
