"""最小Project Export/Import処理のテスト。"""

from __future__ import annotations

import json
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
        self.requests: list[tuple[str, str, object]] = []

    def get_json(self, path: str) -> dict[str, object]:
        """Project情報を返す。"""
        return {"id": 2, "path": "api-service"}

    def request(self, method: str, path: str, **kwargs: object) -> ApiResponse:
        """Export開始、Status、Downloadに応答する。"""
        self.requests.append((method, path, kwargs.get("timeout_seconds")))
        if method == "POST":
            return ApiResponse(202, {}, b"")
        if path.endswith("/export"):
            return ApiResponse(
                200,
                {},
                json.dumps({"export_status": self.statuses.pop(0)}).encode(),
            )
        return ApiResponse(200, {}, self.archive)


class RateLimitedProjectExportClient(ProjectExportClient):
    """最初のDownloadだけ429を返すFakeクライアント。"""

    def __init__(
        self,
        archive: bytes,
        *,
        retry_after: str | None = None,
    ) -> None:
        """ArchiveとRetry-Afterを保持する。"""
        super().__init__(archive)
        self.statuses = ["finished"]
        self.retry_after = retry_after
        self.download_count = 0

    def request(self, method: str, path: str, **kwargs: object) -> ApiResponse:
        """Downloadの初回だけ429を返す。"""
        if path.endswith("/export/download"):
            self.download_count += 1
            if self.download_count == 1:
                headers = (
                    {"Retry-After": self.retry_after}
                    if self.retry_after is not None
                    else {}
                )
                return ApiResponse(429, headers, b'{"message":"too many"}')
        return super().request(method, path, **kwargs)


class ProjectImportClient:
    """Project Import向けFakeクライアント。"""

    def __init__(
        self,
        *,
        failed_relations: list[dict[str, object]] | None = None,
        full_path: str = "destination/subgroup/api-service",
    ) -> None:
        """Import状態とRelation失敗を初期化する。"""
        self.import_statuses = ["scheduled", "finished"]
        self.failed_relations = failed_relations or []
        self.full_path = full_path
        self.submitted_fields: dict[str, object] = {}
        self.upload_timeout: object = None

    @staticmethod
    def encode_id(value: object) -> str:
        """テストでは値をそのまま文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, object]:
        """Namespaceまたは非同期Import状態を返す。"""
        if path == "/groups/35":
            return {"id": 35, "full_path": "destination/subgroup"}
        if self.full_path in path:
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
            "path_with_namespace": self.full_path,
        }

    def post_multipart(self, *args: object, **kwargs: object) -> ApiResponse:
        """Project Import受付レスポンスを返す。"""
        self.submitted_fields = dict(args[1])  # type: ignore[arg-type]
        self.upload_timeout = kwargs.get("timeout_seconds")
        return ApiResponse(202, {}, b'{"id":1,"import_status":"scheduled"}')


class ProjectMigrationTest(unittest.TestCase):
    """Project Exportと非同期Import完了待機を検証する。"""

    def test_exports_after_status_finished(self) -> None:
        """Status APIがfinishedになってからアーカイブを保存する。"""
        archive = tar_gz_bytes("project.json")
        clock = Clock()
        client = ProjectExportClient(archive)
        with tempfile.TemporaryDirectory() as directory:
            result = ProjectExporter(
                client,  # type: ignore[arg-type]
                poll_interval_seconds=2,
                timeout_seconds=10,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(2, Path(directory))
            self.assertEqual(2, clock.value)
            self.assertEqual(len(archive), result.archive_size)
            self.assertEqual(10, client.requests[-1][2])

    def test_waits_sixty_seconds_when_export_download_returns_429(self) -> None:
        """Retry-AfterなしのDownload制限は既定周期の60秒待機する。"""
        archive = tar_gz_bytes("project.json")
        client = RateLimitedProjectExportClient(archive)
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            result = ProjectExporter(
                client,  # type: ignore[arg-type]
                poll_interval_seconds=20,
                timeout_seconds=180,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(2, Path(directory))

        self.assertEqual(60, clock.value)
        self.assertEqual(2, client.download_count)
        self.assertEqual(len(archive), result.archive_size)

    def test_respects_retry_after_for_export_download_429(self) -> None:
        """Download制限にRetry-Afterがあればその秒数以上待機する。"""
        archive = tar_gz_bytes("project.json")
        client = RateLimitedProjectExportClient(archive, retry_after="75")
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            ProjectExporter(
                client,  # type: ignore[arg-type]
                poll_interval_seconds=20,
                timeout_seconds=180,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(2, Path(directory))

        self.assertEqual(75, clock.value)

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

    def test_imports_to_current_users_personal_namespace(self) -> None:
        """Namespace指定を省略して移行先Token利用者の直下へImportする。"""
        client = ProjectImportClient(full_path="destination-user/api-service")
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "project.tar.gz"
            archive.write_bytes(tar_gz_bytes("project.json"))
            result = ProjectImporter(
                client,  # type: ignore[arg-type]
                poll_interval_seconds=3,
                timeout_seconds=10,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).import_project(
                archive,
                name="api-service",
                path="api-service",
                personal_namespace_path="destination-user",
            )

        self.assertEqual("destination-user/api-service", result.full_path)
        self.assertEqual(
            {"name": "api-service", "path": "api-service"},
            client.submitted_fields,
        )
        self.assertEqual(10, client.upload_timeout)


if __name__ == "__main__":
    unittest.main()
