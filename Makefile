TF_DIR := terraform
ENV ?= dev

IMAGE_REGISTRY ?= ghcr.io/jay-withers/career
# Defaults to the local commit, which is what you want when iterating: build,
# push, and the tag you just built is the one you reference.
IMAGE_TAG ?= $(shell git rev-parse --short HEAD)
# `file` means the ?= default fired rather than the caller passing one.
IMAGE_TAG_EXPLICIT := $(filter-out file,$(origin IMAGE_TAG))

.DEFAULT_GOAL := help

.PHONY: help install lint test run import show pipeline pipeline-local build push deploy url logs secrets init fmt validate plan apply

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# Expected to be re-run after a dev container rebuild, not just after a
# clone: uv installs into ~/.local/bin, which is the container's writable
# layer and does not survive one.
install: ## Install pre-commit hooks and Python dependencies
	pre-commit install
	pre-commit install --hook-type commit-msg
	command -v uv >/dev/null || curl -fsSL https://astral.sh/uv/install.sh | sh
	uv sync --extra dev

test: ## Run the test suite
	uv run --extra dev pytest

lint: ## Run every pre-commit hook against every file
	pre-commit run --all-files

# No Azure at all: with no PROFILE_CONTAINER_URL/JOBS_CONTAINER_URL each
# document falls back to a local file, and APP_PASSCODE is read from the
# environment before Key Vault is ever consulted.
run: ## Serve locally on :8000 against local files
	APP_PASSCODE=$${APP_PASSCODE:-local} uv run career serve --reload

# Against the real blobs, so it needs Storage Blob Data Contributor on both
# containers — which whoever applied the Terraform has.
import: ## Import a LinkedIn export against the real profile (FILE=path)
	@if [ -z "$(FILE)" ]; then echo "error: pass FILE=/path/to/export.zip" >&2; exit 1; fi
	PROFILE_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw profile_container_url)" \
		uv run career import "$(FILE)"

show: ## Print the deployed profile and job cache as JSON
	PROFILE_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw profile_container_url)" \
	JOBS_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw jobs_container_url)" \
		uv run career show

pipeline: ## Run the fetch/match/insights pipeline against the real blobs
	PROFILE_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw profile_container_url)" \
	JOBS_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw jobs_container_url)" \
		uv run career pipeline

pipeline-local: ## Run the pipeline against local files only
	PROFILE_CONTAINER_URL= JOBS_CONTAINER_URL= uv run career pipeline

# `--platform linux/amd64` is not optional. Container Apps runs amd64 only.
build: ## Build the image for linux/amd64 (set IMAGE_TAG, defaults to the git SHA)
	docker buildx build --platform linux/amd64 --load \
		-t $(IMAGE_REGISTRY)/career:$(IMAGE_TAG) .

push: ## Push the image to ghcr.io (needs write:packages)
	gh auth token | docker login ghcr.io -u $$(gh api user --jq .login) --password-stdin
	docker push $(IMAGE_REGISTRY)/career:$(IMAGE_TAG)

# A bare `make deploy` is a hard error, unlike build/push: the default would
# silently roll the app onto whatever commit happens to be checked out.
deploy: ## Roll an image tag onto the app and the pipeline job (IMAGE_TAG required)
	@if [ -z "$(IMAGE_TAG_EXPLICIT)" ]; then \
		echo "error: pass a tag explicitly, e.g. make deploy IMAGE_TAG=v0.1.0" >&2; exit 1; fi
	@case "$(IMAGE_TAG)" in latest|main|unset) \
		echo "error: $(IMAGE_TAG) is a moving tag. Container Apps only creates a revision when the template changes, so re-pushing one deploys nothing and reports success." >&2; exit 1;; esac
	terraform -chdir=$(TF_DIR) init -reconfigure -backend-config=backends/$(ENV).hcl
	az containerapp update \
		--name "$$(terraform -chdir=$(TF_DIR) output -raw container_app_name)" \
		--resource-group "$$(terraform -chdir=$(TF_DIR) output -raw resource_group_name)" \
		--image $(IMAGE_REGISTRY)/career:$(IMAGE_TAG) \
		--set-env-vars IMAGE_TAG=$(IMAGE_TAG) \
		PROFILE_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw profile_container_url)" \
		JOBS_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw jobs_container_url)"
	az containerapp job update \
		--name "$$(terraform -chdir=$(TF_DIR) output -raw container_app_job_name)" \
		--resource-group "$$(terraform -chdir=$(TF_DIR) output -raw resource_group_name)" \
		--image $(IMAGE_REGISTRY)/career:$(IMAGE_TAG) \
		--set-env-vars IMAGE_TAG=$(IMAGE_TAG) \
		PROFILE_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw profile_container_url)" \
		JOBS_CONTAINER_URL="$$(terraform -chdir=$(TF_DIR) output -raw jobs_container_url)"

url: ## Print the application's URL
	@terraform -chdir=$(TF_DIR) output -raw app_url; echo

logs: ## Tail the deployed app's logs
	az containerapp logs show \
		--name "$$(terraform -chdir=$(TF_DIR) output -raw container_app_name)" \
		--resource-group "$$(terraform -chdir=$(TF_DIR) output -raw resource_group_name)" \
		--container career --follow

secrets: ## Print the az commands that populate this project's Key Vault
	@echo "az keyvault secret set --vault-name $$(terraform -chdir=$(TF_DIR) output -raw key_vault_name) --name APP-PASSCODE --value <passcode>"
	@echo "az keyvault secret set --vault-name $$(terraform -chdir=$(TF_DIR) output -raw key_vault_name) --name ADZUNA-APP-ID --value <app-id>"
	@echo "az keyvault secret set --vault-name $$(terraform -chdir=$(TF_DIR) output -raw key_vault_name) --name ADZUNA-APP-KEY --value <app-key>"
	@echo "az keyvault secret set --vault-name $$(terraform -chdir=$(TF_DIR) output -raw key_vault_name) --name ANTHROPIC-API-KEY --value <api-key>"

init: ## terraform init, without configuring the state backend
	terraform -chdir=$(TF_DIR) init -backend=false

fmt: ## terraform fmt -recursive
	terraform -chdir=$(TF_DIR) fmt -recursive

validate: init ## terraform init + validate (no Azure credentials needed)
	terraform -chdir=$(TF_DIR) validate

plan: ## terraform init + plan
	terraform -chdir=$(TF_DIR) init -reconfigure -backend-config=backends/$(ENV).hcl
	terraform -chdir=$(TF_DIR) plan -var-file=environments/$(ENV).tfvars

apply: ## terraform init + apply
	terraform -chdir=$(TF_DIR) init -reconfigure -backend-config=backends/$(ENV).hcl
	terraform -chdir=$(TF_DIR) apply -var-file=environments/$(ENV).tfvars
