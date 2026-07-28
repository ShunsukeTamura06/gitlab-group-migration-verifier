"""Group単位のExport、Import、検証フロー制御。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .client import GitLabClient
from .group_exporter import GroupExporter
from .group_importer import GroupImporter
from .group_verifier import GroupVerifier
from .hierarchy import GroupHierarchy
from .manifest import ManifestStore
from .namespace_mapper import NamespaceMapper


class GroupMigrator:
    """トップレベルGroupの移行と検証を一連で実行する。"""

    def __init__(
        self,
        source: GitLabClient,
        destination: GitLabClient,
        *,
        export_dir: Path,
        manifest_path: Path,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 600.0,
    ) -> None:
        """Group移行サービスを初期化する。"""
        self.source = source
        self.destination = destination
        self.export_dir = export_dir
        self.manifest_store = ManifestStore(manifest_path)
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

    def migrate(
        self,
        source_group_id: int,
        *,
        destination_name: str,
        destination_path: str,
        destination_parent_id: int | None = None,
        reuse_existing: bool = False,
    ) -> dict[str, Any]:
        """GroupをExport/Importし、階層とGroupデータを検証する。"""
        started_at = datetime.now(timezone.utc).isoformat()
        source_group = self.source.get_json(f"/groups/{source_group_id}")
        manifest: dict[str, Any] = {
            "tool": {
                "name": "gitlab-group-migrator",
                "version": __version__,
            },
            "state": "group_export_started",
            "source": source_group,
            "destination": None,
            "timestamps": {"started_at": started_at, "finished_at": None},
        }
        self.manifest_store.save(manifest)

        export_result = GroupExporter(
            self.source,
            poll_interval_seconds=self.poll_interval_seconds,
            timeout_seconds=self.timeout_seconds,
        ).export(source_group_id, self.export_dir)
        manifest.update({"state": "group_archive_downloaded", "export": export_result.to_dict()})
        self.manifest_store.save(manifest)

        manifest["state"] = "group_import_started"
        self.manifest_store.save(manifest)
        import_result = GroupImporter(
            self.destination,
            poll_interval_seconds=self.poll_interval_seconds,
            timeout_seconds=self.timeout_seconds,
        ).import_group(
            export_result.archive_path,
            name=destination_name,
            path=destination_path,
            parent_id=destination_parent_id,
            reuse_existing=reuse_existing,
        )
        destination_group = self.destination.get_json(f"/groups/{import_result.group_id}")
        manifest.update(
            {
                "state": "group_import_finished",
                "destination": destination_group,
                "import": asdict(import_result),
            }
        )
        self.manifest_store.save(manifest)

        verification = GroupVerifier(self.source, self.destination).verify(
            source_group_id, import_result.group_id
        )
        source_tree = GroupHierarchy(self.source).fetch(source_group_id)
        destination_tree = GroupHierarchy(self.destination).fetch(import_result.group_id)
        mapper = NamespaceMapper.from_trees(source_tree, destination_tree)
        manifest.update(
            {
                "state": "group_verification_finished",
                "hierarchy": {
                    "source_group_count": len(source_tree),
                    "destination_group_count": len(destination_tree),
                    "mappings": [asdict(item) for item in mapper.mappings],
                },
                "verification": verification.to_dict(),
                "timestamps": {
                    "started_at": started_at,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            }
        )
        self.manifest_store.save(manifest)
        return manifest
