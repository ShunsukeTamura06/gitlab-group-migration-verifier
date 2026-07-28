"""最小Project Export/Import処理のテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gitlab_migrator.client import ApiResponse
from gitlab_migrator.errors import GitLabApiError
from gitlab_migrator.project_exporter import ProjectExporter
from gitlab_migrator.project_importer import ProjectImporter

from tests.helpers import Clock, tar_gz_bytes


class ProjectExportClient:
    """Project Export向けFakeクライアント。"""

    def __init__(self, archive: bytes) -> None:
        """アーカイブとStatus列を保持する。"""
        self.archive = archive
        self.statuses = ["started", "finished"]

    def get_json(self, path: str) -> dict[str, object]:
        """ProjectまたはExport Statusを返す。"""
        if path.endswith("/export"):
            return {"export_status": self.statuses.pop(0)}
        return {"id": 2, "path": "api-service"}

    def request(self, method: str, path: str, **_kwargs: object) -> ApiResponse:
        """Export開始とDownloadに応答する。"""
        if method == "POST":
            return ApiResponse(202, {}, b"")
        return ApiResponse(200, {}, self.archive)


class ProjectImportClient:
    """Project Import向けFakeクライアント。"""

    def __init__(self, *, failed_relations: list[dict[str, object]] | None = None) -> None:
        """Import状態とRelation失敗を初期化する。"""
        self.import_statuses = ["scheduled", "finished"]
        self.failed_relations = failed_relations or []

    @staticmethod
    def encode_id(value: object) -> str:
        """テストでは値をそのまま文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, object]:
        """Namespaceまたは非同期Import状態を返す。"""
        if path == "/groups/35":
            return {"id": 35, "full_path": "destination/subgroup"}
        if "destination/subgroup/api-service" in path:
            raise GitLabApiError("not found", status=404)
        if path == "/projects/1/import":
            status = self.import_statuses.pop(0)
            return {
                "id": 1,
                "import_status": status,
                "correlation_id": "migration-123",
                "import_error": None,
                "failed_relations": (
                    self.failed_relations if status == "finished" else []
                ),
            }
        return {
            "id": 1,
            "path_with_namespace": "destination/subgroup/api-service",
        }

    def post_multipart(self, *_args: object, **_kwargs: object) -> ApiResponse:
        """Project Import受付レスポンスを返す。"""
        return ApiResponse(202, {}, b'{"id":1,"import_status":"scheduled"}')


class ProjectMigrationTest(unittest.TestCase):
    """Project Exportと非同期Import完了待機を検証する。"""

    def test_exports_after_status_finished(self) -> None:
        """Status APIがfinishedになってからアーカイブを保存する。"""
        archive = tar_gz_bytes("project.json")
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            result = ProjectExporter(
                ProjectExportClient(archive),  # type: ignore[arg-type]
                poll_interval_seconds=2,
                timeout_seconds=10,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(2, Path(directory))
            self.assertEqual(2, clock.value)
            self.assertEqual(len(archive), result.archive_size)

    def test_waits_until_import_status_finished(self) -> None:
        """Project作成直後のscheduledを完了扱いしない。"""
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "project.tar.gz"
            archive.write_bytes(tar_gz_bytes("project.json"))
            result = ProjectImporter(
                ProjectImportClient(),  # type: ignore[arg-type]
                poll_interval_seconds=3,
                timeout_seconds=10,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).import_project(
                archive,
                name="api-service",
                path="api-service",
                namespace_id=35,
            )
        self.assertEqual(3, clock.value)
        self.assertEqual("destination/subgroup/api-service", result.full_path)
        self.assertEqual([], result.failed_relations)
        self.assertEqual("migration-123", result.correlation_id)

    def test_rejects_finished_import_with_failed_relations(self) -> None:
        """StatusがfinishedでもRelation失敗があれば成功扱いしない。"""
        failed_relations = [
            {
                "relation_name": "merge_requests",
                "exception_class": "RuntimeError",
                "exception_message": "query timeout",
            }
        ]
        client = ProjectImportClient(failed_relations=failed_relations)
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "project.tar.gz"
            archive.write_bytes(tar_gz_bytes("project.json"))
            with self.assertRaisesRegex(
                GitLabApiError,
                "merge_requests",
            ):
                ProjectImporter(
                    client,  # type: ignore[arg-type]
                    poll_interval_seconds=3,
                    timeout_seconds=10,
                    sleep=clock.sleep,
                    monotonic=clock.monotonic,
                ).import_project(
                    archive,
                    name="api-service",
                    path="api-service",
                    namespace_id=35,
                )


if __name__ == "__main__":
    unittest.main()
