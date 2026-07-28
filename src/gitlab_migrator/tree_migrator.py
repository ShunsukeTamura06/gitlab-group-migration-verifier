"""Group階層と配下の全Projectを一括または二段階で移行する。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .client import GitLabClient
from .errors import ArchiveValidationError, TreeVerificationError
from .group_exporter import GroupExporter
from .group_importer import GroupImporter
from .group_verifier import GroupVerifier
from .hierarchy import GroupHierarchy
from .manifest import ManifestStore
from .namespace_mapper import NamespaceMapper
from .project_exporter import ProjectExporter
from .project_importer import ProjectImporter
from .project_verifier import ProjectTreeVerifier


def _utcnow() -> str:
    """現在のUTC時刻をISO 8601形式で返す。"""
    return datetime.now(timezone.utc).isoformat()


class TreeBundleExporter:
    """移行元だけに接続し、Groupと全Projectの移行Bundleを作る。"""

    def __init__(
        self,
        source: GitLabClient,
        *,
        group_export_dir: Path,
        project_export_dir: Path,
        manifest_path: Path,
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Exporterを初期化する。"""
        self.source = source
        self.group_export_dir = group_export_dir
        self.project_export_dir = project_export_dir
        self.manifest_store = ManifestStore(manifest_path)
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def export(
        self,
        source_group_id: int,
        *,
        include_projects: bool = True,
    ) -> dict[str, Any]:
        """Groupと配下の全ProjectをExportし、移送可能なManifestを作る。"""
        started_at = _utcnow()
        manifest: dict[str, Any] = {
            "tool": {
                "name": "gitlab-group-migrator",
                "version": __version__,
            },
            "state": "not_started",
            "status": "running",
            "source": {"group_id": source_group_id},
            "destination": None,
            "projects": [],
            "timestamps": {
                "started_at": started_at,
                "export_finished_at": None,
                "finished_at": None,
            },
        }
        self.manifest_store.save(manifest)
        try:
            source_snapshot = GroupVerifier.capture(self.source, source_group_id)
            source_nodes = GroupVerifier.snapshot_nodes(source_snapshot)
            if include_projects:
                project_snapshot = ProjectTreeVerifier.capture(
                    self.source,
                    source_group_id,
                    nodes=source_nodes,
                )
            else:
                root = next(node for node in source_nodes if node.relative_path == ".")
                project_snapshot = {
                    "root_group_id": source_group_id,
                    "root_full_path": root.full_path,
                    "project_count": 0,
                    "projects": [],
                }
            manifest.update(
                {
                    "state": "group_export_started",
                    "source": {
                        "group_id": source_group_id,
                        "group_snapshot": source_snapshot,
                        "project_snapshot": project_snapshot,
                        "group_count": len(source_nodes),
                        "project_count": project_snapshot["project_count"],
                        "include_projects": include_projects,
                    },
                }
            )
            self.manifest_store.save(manifest)

            group_export = GroupExporter(
                self.source,
                poll_interval_seconds=self.poll_interval_seconds,
                timeout_seconds=self.timeout_seconds,
                sleep=self._sleep,
                monotonic=self._monotonic,
            ).export(source_group_id, self.group_export_dir)
            manifest.update(
                {
                    "state": "group_archive_downloaded",
                    "export": group_export.to_dict(),
                }
            )
            self.manifest_store.save(manifest)

            for project in project_snapshot["projects"]:
                project_id = int(project["id"])
                export_result = ProjectExporter(
                    self.source,
                    poll_interval_seconds=self.poll_interval_seconds,
                    timeout_seconds=self.timeout_seconds,
                    sleep=self._sleep,
                    monotonic=self._monotonic,
                ).export(project_id, self.project_export_dir)
                manifest["projects"].append(
                    {
                        "source_project_id": project_id,
                        "source_path": project["path_with_namespace"],
                        "source_relative_path": project["relative_path"],
                        "source": project,
                        "archive": export_result.to_dict(),
                        "migration_status": "export_finished",
                        "verification_status": "not_started",
                    }
                )
                self.manifest_store.save(manifest)

            manifest.update(
                {
                    "state": "tree_export_finished",
                    "status": "exported",
                    "timestamps": {
                        **manifest["timestamps"],
                        "export_finished_at": _utcnow(),
                    },
                }
            )
            self.manifest_store.save(manifest)
            return manifest
        except Exception as exc:
            self._save_failure(manifest, exc)
            raise

    def _save_failure(self, manifest: dict[str, Any], exc: Exception) -> None:
        """失敗理由と完了時刻をManifestへ保存する。"""
        manifest.update(
            {
                "state": "failed",
                "status": "failed",
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "timestamps": {
                    **manifest["timestamps"],
                    "finished_at": _utcnow(),
                },
            }
        )
        self.manifest_store.save(manifest)


class TreeBundleImporter:
    """Export済みBundleを移行先へImportし、全Projectを突合する。"""

    def __init__(
        self,
        destination: GitLabClient,
        *,
        manifest_path: Path,
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Importerを初期化する。"""
        self.destination = destination
        self.manifest_store = ManifestStore(manifest_path)
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def import_bundle(
        self,
        *,
        destination_name: str,
        destination_path: str,
        destination_parent_id: int | None = None,
        reuse_existing_group: bool = False,
    ) -> dict[str, Any]:
        """Bundle内のGroupと全ProjectをImportして最終比較する。"""
        manifest = self.manifest_store.load()
        timestamps = manifest.get("timestamps")
        if not isinstance(timestamps, dict):
            raise ValueError("Tree Manifestにtimestampsがありません")
        try:
            source = manifest.get("source")
            if not isinstance(source, dict):
                raise ValueError("Tree Manifestにsourceがありません")
            source_snapshot = source.get("group_snapshot")
            project_snapshot = source.get("project_snapshot")
            if not isinstance(source_snapshot, dict):
                raise ValueError("Tree ManifestにGroup Snapshotがありません")
            if not isinstance(project_snapshot, dict):
                raise ValueError("Tree ManifestにProject Snapshotがありません")
            source_nodes = GroupVerifier.snapshot_nodes(source_snapshot)
            project_records = manifest.get("projects")
            if not isinstance(project_records, list):
                raise ValueError("Tree Manifestにprojects配列がありません")
            expected_projects = int(project_snapshot.get("project_count") or 0)
            if len(project_records) != expected_projects:
                raise ValueError(
                    "Project Export件数がSnapshotと一致しません: "
                    f"snapshot={expected_projects}, exports={len(project_records)}"
                )
            self._validate_archive(manifest.get("export"), "Group")
            for record in project_records:
                if not isinstance(record, dict):
                    raise ValueError("Project Manifest要素がオブジェクトではありません")
                self._validate_archive(record.get("archive"), "Project")

            manifest.pop("error", None)
            manifest.update(
                {
                    "state": "group_import_started",
                    "status": "running",
                    "request": {
                        "destination_name": destination_name,
                        "destination_path": destination_path,
                        "destination_parent_id": destination_parent_id,
                    },
                }
            )
            self.manifest_store.save(manifest)
            group_archive = Path(str(manifest["export"]["archive_path"]))
            group_import = GroupImporter(
                self.destination,
                poll_interval_seconds=self.poll_interval_seconds,
                timeout_seconds=self.timeout_seconds,
                sleep=self._sleep,
                monotonic=self._monotonic,
            ).import_group(
                group_archive,
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

            destination_snapshot = self._wait_for_stable_group_snapshot(
                group_import.group_id,
                expected_group_count=len(source_nodes),
            )
            group_verification = GroupVerifier.compare_snapshots(
                source_snapshot,
                destination_snapshot,
            )
            destination_nodes = GroupVerifier.snapshot_nodes(destination_snapshot)
            mapper = NamespaceMapper.from_trees(source_nodes, destination_nodes)
            manifest.update(
                {
                    "state": "group_verification_finished",
                    "verification": group_verification.to_dict(),
                    "hierarchy": {
                        "source_group_count": len(source_nodes),
                        "destination_group_count": len(destination_nodes),
                        "mappings": [asdict(item) for item in mapper.mappings],
                    },
                }
            )
            self.manifest_store.save(manifest)

            if group_verification.missing_groups or group_verification.extra_groups:
                raise TreeVerificationError(
                    "Group階層にMissingまたはExtraがあるためProject移行を中止しました"
                )

            manifest["state"] = "projects_migration_started"
            self.manifest_store.save(manifest)
            for record in project_records:
                self._import_project(record, mapper)
                self.manifest_store.save(manifest)
            manifest["state"] = "projects_migration_finished"
            self.manifest_store.save(manifest)

            destination_project_snapshot = ProjectTreeVerifier.capture(
                self.destination,
                group_import.group_id,
                nodes=destination_nodes,
            )
            project_verification = ProjectTreeVerifier.compare_snapshots(
                project_snapshot,
                destination_project_snapshot,
            )
            manifest.update(
                {
                    "project_verification": project_verification.to_dict(),
                    "destination_project_snapshot": destination_project_snapshot,
                }
            )
            if project_verification.status == "failed":
                self.manifest_store.save(manifest)
                raise TreeVerificationError(
                    "全Project比較で欠落、余分、または重大な属性差分を検出しました"
                )

            overall_status = (
                "warning"
                if group_verification.status == "warning"
                or project_verification.status == "warning"
                else "success"
            )
            manifest.update(
                {
                    "state": "tree_verification_finished",
                    "status": overall_status,
                    "timestamps": {
                        **timestamps,
                        "finished_at": _utcnow(),
                    },
                }
            )
            self.manifest_store.save(manifest)
            return manifest
        except Exception as exc:
            manifest.update(
                {
                    "state": "failed",
                    "status": "failed",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "timestamps": {
                        **timestamps,
                        "finished_at": _utcnow(),
                    },
                }
            )
            self.manifest_store.save(manifest)
            raise

    def _import_project(
        self,
        record: dict[str, Any],
        mapper: NamespaceMapper,
    ) -> None:
        """1 Projectを対応NamespaceへImportし、即時配置を確認する。"""
        source_project = record.get("source")
        archive = record.get("archive")
        if not isinstance(source_project, dict) or not isinstance(archive, dict):
            raise ValueError("Project ManifestにSourceまたはArchive情報がありません")
        source_path = str(source_project["path_with_namespace"])
        source_namespace = source_path.rsplit("/", 1)[0]
        destination_namespace = mapper.destination_namespace(source_namespace)
        destination_mapping = next(
            item
            for item in mapper.mappings
            if item.destination_full_path == destination_namespace
        )
        imported = ProjectImporter(
            self.destination,
            poll_interval_seconds=self.poll_interval_seconds,
            timeout_seconds=self.timeout_seconds,
            sleep=self._sleep,
            monotonic=self._monotonic,
        ).import_project(
            Path(str(archive["archive_path"])),
            name=str(source_project["name"]),
            path=str(source_project["path"]),
            namespace_id=destination_mapping.destination_group_id,
        )
        expected_path = mapper.destination_project_path(source_path)
        verification_status = (
            "success" if imported.full_path == expected_path else "failed"
        )
        record.update(
            {
                "import": asdict(imported),
                "destination_project_id": imported.project_id,
                "destination_path": imported.full_path,
                "expected_destination_path": expected_path,
                "migration_status": "finished",
                "verification_status": verification_status,
            }
        )
        if verification_status == "failed":
            raise TreeVerificationError(
                f"Projectの移行先Namespaceが不正です: "
                f"expected={expected_path}, actual={imported.full_path}"
            )

    def _wait_for_stable_group_snapshot(
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

    @staticmethod
    def _validate_archive(payload: Any, label: str) -> None:
        """Manifest記載のArchiveについて存在、形式、サイズ、SHA-256を確認する。"""
        if not isinstance(payload, dict):
            raise ArchiveValidationError(f"{label} Archive情報がありません")
        path = Path(str(payload.get("archive_path") or ""))
        if not path.is_file():
            raise ArchiveValidationError(f"{label} Archiveが存在しません: {path}")
        GroupExporter._validate_archive(path)
        expected_size = int(payload.get("archive_size") or -1)
        if path.stat().st_size != expected_size:
            raise ArchiveValidationError(
                f"{label} ArchiveのサイズがManifestと一致しません: {path}"
            )
        expected_sha256 = str(payload.get("sha256") or "")
        if GroupExporter._sha256(path) != expected_sha256:
            raise ArchiveValidationError(
                f"{label} ArchiveのSHA-256がManifestと一致しません: {path}"
            )


class TreeMigrator:
    """SourceとDestinationへ同時接続し、全Project移行を一括実行する。"""

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
        self.exporter = TreeBundleExporter(
            source,
            group_export_dir=group_export_dir,
            project_export_dir=project_export_dir,
            manifest_path=manifest_path,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            sleep=sleep,
            monotonic=monotonic,
        )
        self.importer = TreeBundleImporter(
            destination,
            manifest_path=manifest_path,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            sleep=sleep,
            monotonic=monotonic,
        )

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
        """Groupと配下の全ProjectをExport、Import、最終突合する。"""
        self.exporter.export(
            source_group_id,
            include_projects=include_projects,
        )
        return self.importer.import_bundle(
            destination_name=destination_name,
            destination_path=destination_path,
            destination_parent_id=destination_parent_id,
            reuse_existing_group=reuse_existing_group,
        )
