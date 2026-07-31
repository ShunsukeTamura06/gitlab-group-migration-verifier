"""全Project一括ExportとBundle検証のテスト。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from gitlab_migrator import __version__
from gitlab_migrator.client import ApiResponse
from gitlab_migrator.errors import ArchiveValidationError
from gitlab_migrator.group_exporter import GroupExporter
from gitlab_migrator.manifest import ManifestStore
from gitlab_migrator.tree_migrator import TreeBundleExporter, TreeBundleImporter
from tests.helpers import Clock, tar_gz_bytes


class TreeExportClient:
    """Groupと2 ProjectのExport APIを返すFakeクライアント。"""

    def __init__(self) -> None:
        """検証用tar.gzを保持する。"""
        self.archive = tar_gz_bytes("tree/project.json")

    @staticmethod
    def encode_id(value: object) -> str:
        """IDを文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, Any]:
        """Group、Project、Project Export Statusを返す。"""
        if path.endswith("/export"):
            return {"export_status": "finished"}
        if path == "/groups/1":
            return {
                "id": 1,
                "name": "source",
                "path": "source",
                "full_path": "source",
                "parent_id": None,
                "description": "root",
                "visibility": "private",
            }
        if path == "/projects/10":
            return self._project(10, "source/root-project", 1)
        if path == "/projects/11":
            return self._project(11, "source/backend/api-service", 2)
        raise AssertionError(path)

    def list_all(
        self,
        path: str,
        **_kwargs: object,
    ) -> list[dict[str, Any]]:
        """Subgroup、Groupデータ、直下Projectを返す。"""
        if path == "/groups/1/subgroups":
            return [
                {
                    "id": 2,
                    "name": "backend",
                    "path": "backend",
                    "full_path": "source/backend",
                    "parent_id": 1,
                    "description": "backend",
                    "visibility": "private",
                }
            ]
        if path == "/groups/2/subgroups":
            return []
        if path.endswith(("/labels", "/milestones")):
            return []
        if path == "/groups/1/projects":
            return [self._project(10, "source/root-project", 1)]
        if path == "/groups/2/projects":
            return [self._project(11, "source/backend/api-service", 2)]
        raise AssertionError(path)

    def request(self, method: str, path: str, **_kwargs: object) -> ApiResponse:
        """Export開始、Status、Downloadへ応答する。"""
        if method == "POST":
            return ApiResponse(202, {}, b"")
        if path.endswith("/download"):
            return ApiResponse(200, {}, self.archive)
        if path.endswith("/export"):
            return ApiResponse(
                200,
                {},
                json.dumps({"export_status": "finished"}).encode(),
            )
        raise AssertionError((method, path))

    @staticmethod
    def _project(project_id: int, full_path: str, namespace_id: int) -> dict[str, Any]:
        """Project API応答を作る。"""
        path = full_path.rsplit("/", 1)[1]
        return {
            "id": project_id,
            "name": path,
            "path": path,
            "path_with_namespace": full_path,
            "namespace": {"id": namespace_id},
            "description": f"description:{path}",
            "visibility": "private",
            "archived": False,
            "default_branch": "main",
            "empty_repo": False,
        }


class TreeMigratorTest(unittest.TestCase):
    """全Project Exportと破損Bundle拒否を検証する。"""

    def test_exports_every_project_and_records_each_archive(self) -> None:
        """異なる階層の全ProjectをExportしManifestへ即時記録する。"""
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "tree.json"
            result = TreeBundleExporter(
                TreeExportClient(),  # type: ignore[arg-type]
                group_export_dir=root / "groups",
                project_export_dir=root / "projects",
                manifest_path=manifest_path,
                poll_interval_seconds=1,
                timeout_seconds=10,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(1)
            self.assertEqual("tree_export_finished", result["state"])
            self.assertEqual(__version__, result["tool"]["version"])
            self.assertEqual(2, result["source"]["project_count"])
            self.assertEqual(2, len(result["projects"]))
            self.assertEqual(
                {"root-project", "backend/api-service"},
                {
                    record["source_relative_path"]
                    for record in result["projects"]
                },
            )
            for record in result["projects"]:
                self.assertTrue(Path(record["archive"]["archive_path"]).is_file())
                self.assertEqual("export_finished", record["migration_status"])

    def test_import_rejects_archive_changed_after_export(self) -> None:
        """搬送後にサイズが変わったProject ArchiveをImport前に拒否する。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group_archive = root / "group.tar.gz"
            project_archive = root / "project.tar.gz"
            group_archive.write_bytes(tar_gz_bytes("tree/group.json"))
            project_archive.write_bytes(tar_gz_bytes("tree/project.json"))
            manifest_path = root / "tree.json"
            ManifestStore(manifest_path).save(
                {
                    "state": "tree_export_finished",
                    "source": {
                        "group_id": 1,
                        "group_snapshot": {
                            "root_group_id": 1,
                            "groups": [
                                {
                                    "id": 1,
                                    "name": "source",
                                    "path": "source",
                                    "full_path": "source",
                                    "parent_id": None,
                                    "relative_path": ".",
                                    "depth": 0,
                                    "description": "",
                                    "visibility": "private",
                                    "labels": [],
                                    "milestones": [],
                                }
                            ],
                        },
                        "project_snapshot": {
                            "project_count": 1,
                            "projects": [{"relative_path": "api-service"}],
                        },
                    },
                    "projects": [
                        {
                            "archive": self._archive_payload(project_archive),
                        }
                    ],
                    "export": self._archive_payload(group_archive),
                    "timestamps": {"started_at": "now"},
                }
            )
            with project_archive.open("ab") as stream:
                stream.write(b"tampered")
            importer = TreeBundleImporter(  # type: ignore[arg-type]
                object(),
                manifest_path=manifest_path,
            )
            with self.assertRaises(ArchiveValidationError):
                importer.import_bundle(
                    destination_name="destination",
                    destination_path="destination",
                )

    @staticmethod
    def _archive_payload(path: Path) -> dict[str, Any]:
        """ArchiveのサイズとSHA-256をManifest形式で返す。"""
        return {
            "archive_path": str(path),
            "archive_size": path.stat().st_size,
            "sha256": GroupExporter._sha256(path),
        }


if __name__ == "__main__":
    unittest.main()
