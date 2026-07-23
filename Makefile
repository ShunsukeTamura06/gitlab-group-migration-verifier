PYTHON ?= python3
CLI := PYTHONPATH=src $(PYTHON) -m gitlab_migrator.cli
SOURCE_GROUP_ID ?=
DESTINATION_GROUP_ID ?=
DESTINATION_PATH ?= migration-destination

.PHONY: help up down wait test compile preflight bootstrap-groups smoke-groups migrate-groups verify-groups migrate-tree verify-tree report-tree all

help:
	@$(CLI) --help

up:
	docker compose up -d

down:
	docker compose down

wait:
	@./scripts/wait_for_gitlab.sh gitlab-migration-source http://localhost:8081
	@./scripts/wait_for_gitlab.sh gitlab-migration-destination http://localhost:8082

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

compile:
	PYTHONPATH=src $(PYTHON) -m compileall -q src tests

preflight:
	$(CLI) preflight

bootstrap-groups:
	$(CLI) bootstrap-groups

smoke-groups:
	$(CLI) smoke-group

migrate-groups:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	$(CLI) migrate-group --source-group-id $(SOURCE_GROUP_ID) --destination-path $(DESTINATION_PATH) --exclude-projects

verify-groups:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	@test -n "$(DESTINATION_GROUP_ID)" || (echo "DESTINATION_GROUP_ID is required" >&2; exit 2)
	$(CLI) verify-group --source-group-id $(SOURCE_GROUP_ID) --destination-group-id $(DESTINATION_GROUP_ID)

migrate-tree:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	$(CLI) migrate-tree --source-group-id $(SOURCE_GROUP_ID) --destination-path $(DESTINATION_PATH) --include-projects

verify-tree: verify-groups

report-tree:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	$(CLI) report --source-group-id $(SOURCE_GROUP_ID)

all: compile test
	@echo "実機検証は make smoke-groups で明示的に実行してください。"
