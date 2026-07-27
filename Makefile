PYTHON ?= python3
CLI := PYTHONPATH=src $(PYTHON) -m gitlab_migrator.cli
SOURCE_GROUP_ID ?=
DESTINATION_GROUP_ID ?=
DESTINATION_PATH ?= migration-destination
TREE_MANIFEST ?= work/manifests/tree-$(SOURCE_GROUP_ID).json

.PHONY: help test compile preflight migrate-groups verify-groups migrate-tree export-tree import-tree verify-tree report-tree all

help:
	@$(CLI) --help

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

compile:
	PYTHONPATH=src $(PYTHON) -m compileall -q src tests

preflight:
	$(CLI) preflight

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

export-tree:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	$(CLI) export-tree --source-group-id $(SOURCE_GROUP_ID) --manifest $(TREE_MANIFEST)

import-tree:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	$(CLI) import-tree --manifest $(TREE_MANIFEST) --destination-path $(DESTINATION_PATH)

verify-tree:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	@test -n "$(DESTINATION_GROUP_ID)" || (echo "DESTINATION_GROUP_ID is required" >&2; exit 2)
	$(CLI) verify-tree --source-group-id $(SOURCE_GROUP_ID) --destination-group-id $(DESTINATION_GROUP_ID)

report-tree:
	@test -n "$(SOURCE_GROUP_ID)" || (echo "SOURCE_GROUP_ID is required" >&2; exit 2)
	$(CLI) report --source-group-id $(SOURCE_GROUP_ID)

all: compile test
