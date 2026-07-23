"""Group階層と配下Projectを一連で移行する。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .client import GitLabClient
from .group_exporter import GroupExporter
from .group_importer import GroupImporter
from .group_verifier import GroupVerifier
from .hierarchy import GroupHierarchy
from .manifest import ManifestStore
from .namespace_mapper import NamespaceMapper
from .project_exporter import ProjectExporter
from .project_importer import ProjectImporter


class TreeMigrator:
    """Groupを先にImportし、Projectを対応Namespaceへ個別Importする。"""

    def __init__(
        self,
        source: GitLabClient,
        destination: GitLabClient,
        *,
        group_export_dir: Path,
        project_export_dir: Path,
        manifest_path: Path,
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Tree Migratorを初期化する。"""
        self.source = source
        self.destination = destination
        self.group_export_dir = group_export_dir
        self.project_export_dir = project_export_dir
        self.manifest_store = ManifestStore(manifest_path)
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def migrate(
        self,
        source_group_id: int,
        *,
        destination_name: str,
        destination_path: str,
        destination_parent_id: int | None = None,
        include_projects: bool = True,
        reuse_existing_group: bool = False,
    ) -> dict[str, Any]:
        """Groupツリーを移行し、必要なら全Projectを個別移行する。"""
        started_at = datetime.now(timezone.utc).isoformat()
        manifest: dict[str, Any] = {
            "state": "not_started",
            "source": {"group_id": source_group_id},
            "destination": None,
            "projects": [],
            "timestamps": {"started_at": started_at, "finished_at": None},
        }
        self.manifest_store.save(manifest)
        try:
            source_snapshot = GroupVerifier.capture(self.source, source_group_id)
            source_nodes = GroupHierarchy(self.source).fetch(source_group_id)
            projects = self._list_projects(source_nodes) if include_projects else []
            manifest.update(
                {
                    "state": "group_export_started",
                    "source": {
                        "group_id": source_group_id,
                        "snapshot": source_snapshot,
                        "project_count": len(projects),
                    },
                }
            )
            self.manifest_store.save(manifest)

            group_export = GroupExporter(
                self.source,
                poll_interval_seconds=self.poll_interval_seconds,
                timeout_seconds=self.timeout_seconds,
            ).export(source_group_id, self.group_export_dir)
            manifest.update(
                {"state": "group_archive_downloaded", "export": group_export.to_dict()}
            )
            self.manifest_store.save(manifest)

            project_exports: dict[int, dict[str, Any]] = {}
            if include_projects:
                for project in projects:
                    export_result = ProjectExporter(
                        self.source,
                        poll_interval_seconds=self.poll_interval_seconds,
                        timeout_seconds=self.timeout_seconds,
                    ).export(int(project["id"]), self.project_export_dir)
                    project_exports[int(project["id"])] = export_result.to_dict()

            manifest["state"] = "group_import_started"
            self.manifest_store.save(manifest)
            group_import = GroupImporter(
                self.destination,
                poll_interval_seconds=self.poll_interval_seconds,
                timeout_seconds=self.timeout_seconds,
            ).import_group(
                group_export.archive_path,
                name=destination_name,
                path=destination_path,
                parent_id=destination_parent_id,
                reuse_existing=reuse_existing_group,
            )
            manifest.update(
                {
                    "state": "group_import_finished",
                    "destination": {
                        "group_id": group_import.group_id,
                        "full_path": group_import.full_path,
                    },
                    "import": asdict(group_import),
                }
            )
            self.manifest_store.save(manifest)

            destination_snapshot = self._wait_for_stable_snapshot(
                group_import.group_id,
                expected_group_count=len(source_nodes),
            )
            verification = GroupVerifier.compare_snapshots(
                source_snapshot, destination_snapshot
            )
            destination_nodes = GroupHierarchy(self.destination).fetch(group_import.group_id)
            mapper = NamespaceMapper.from_trees(source_nodes, destination_nodes)
            manifest.update(
                {
                    "state": "group_verification_finished",
                    "verification": verification.to_dict(),
                    "hierarchy": {
                        "mappings": [asdict(item) for item in mapper.mappings],
                    },
                }
            )
            self.manifest_store.save(manifest)

            if include_projects:
                manifest["state"] = "projects_migration_started"
                self.manifest_store.save(manifest)
                for project in projects:
                    source_project_id = int(project["id"])
                    source_namespace = str(project["path_with_namespace"]).rsplit("/", 1)[0]
                    destination_namespace = mapper.destination_namespace(source_namespace)
                    destination_group = next(
                        item
                        for item in mapper.mappings
                        if item.destination_full_path == destination_namespace
                    )
                    imported = ProjectImporter(
                        self.destination,
                        poll_interval_seconds=self.poll_interval_seconds,
                        timeout_seconds=self.timeout_seconds,
                    ).import_project(
                        Path(project_exports[source_project_id]["archive_path"]),
                        name=str(project["name"]),
                        path=str(project["path"]),
                        namespace_id=destination_group.destination_group_id,
                    )
                    expected_path = mapper.destination_project_path(
                        str(project["path_with_namespace"])
                    )
                    manifest["projects"].append(
                        {
                            "source_project_id": source_project_id,
                            "source_path": project["path_with_namespace"],
                            "destination_project_id": imported.project_id,
                            "destination_path": imported.full_path,
                            "expected_destination_path": expected_path,
                            "archive": project_exports[source_project_id],
                            "migration_status": "finished",
                            "verification_status": (
                                "success" if imported.full_path == expected_path else "failed"
                            ),
                        }
                    )
                    self.manifest_store.save(manifest)
                manifest["state"] = "projects_migration_finished"

            manifest.update(
                {
                    "state": "tree_verification_finished",
                    "timestamps": {
                        "started_at": started_at,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            )
            self.manifest_store.save(manifest)
            return manifest
        except Exception as exc:
            manifest.update(
                {
                    "state": "failed",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "timestamps": {
                        "started_at": started_at,
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            )
            self.manifest_store.save(manifest)
            raise

    def _list_projects(self, nodes: list[Any]) -> list[dict[str, Any]]:
        """各Group直下のProjectを重複なく列挙する。"""
        projects: dict[int, dict[str, Any]] = {}
        for node in nodes:
            for project in self.source.list_all(
                f"/groups/{node.id}/projects",
                params={"include_subgroups": "false", "with_shared": "false"},
            ):
                projects[int(project["id"])] = project
        return sorted(projects.values(), key=lambda item: str(item["path_with_namespace"]))

    def _wait_for_stable_snapshot(
        self,
        group_id: int,
        *,
        expected_group_count: int,
    ) -> dict[str, Any]:
        """Import後のGroupデータが30秒以上変化しなくなるまで待つ。"""
        started = self._monotonic()
        previous_signature: str | None = None
        stable_samples = 0
        latest: dict[str, Any] = {}
        while self._monotonic() - started < self.timeout_seconds:
            latest = GroupVerifier.capture(self.destination, group_id)
            signature = json.dumps(latest, ensure_ascii=False, sort_keys=True)
            if signature == previous_signature:
                stable_samples += 1
            else:
                stable_samples = 0
                previous_signature = signature
            elapsed = self._monotonic() - started
            group_count = len(latest.get("groups") or [])
            if (
                elapsed >= 30
                and group_count >= expected_group_count
                and stable_samples >= 2
            ):
                return latest
            self._sleep(self.poll_interval_seconds)
        raise TimeoutError("Import後Groupデータが安定する前にタイムアウトしました")
