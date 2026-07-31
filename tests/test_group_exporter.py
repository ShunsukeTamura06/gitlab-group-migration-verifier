"""Group Export処理のテスト。"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from gitlab_migrator.client import ApiResponse
from gitlab_migrator.errors import ArchiveValidationError, ExportTimeoutError
from gitlab_migrator.group_exporter import GroupExporter
from tests.helpers import Clock, tar_gz_bytes


class ExportClient:
    """GroupExporter向けFakeクライアント。"""

    def __init__(self, downloads: list[ApiResponse]) -> None:
        """Download APIレスポンス列を保持する。"""
        self.downloads = downloads
        self.export_started = False
        self.request_timeouts: list[object] = []

    @staticmethod
    def encode_id(value: int) -> str:
        """IDを文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, object]:
        """存在確認用Groupを返す。"""
        self.last_get = path
        return {"id": 10, "path": "日本語グループ"}

    def request(self, method: str, path: str, **kwargs: object) -> ApiResponse:
        """Export開始またはDownload結果を返す。"""
        self.request_timeouts.append(kwargs.get("timeout_seconds"))
        if method == "POST":
            self.export_started = True
            return ApiResponse(202, {}, b"")
        return self.downloads.pop(0)


class GroupExporterTest(unittest.TestCase):
    """Exportのポーリング、検証、保存を検証する。"""

    def test_polls_404_then_saves_valid_archive(self) -> None:
        """404を生成中として待ち、200のtar.gzを保存する。"""
        archive = tar_gz_bytes()
        client = ExportClient(
            [ApiResponse(404, {}, b""), ApiResponse(200, {}, archive)]
        )
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            result = GroupExporter(
                client,  # type: ignore[arg-type]
                poll_interval_seconds=1,
                timeout_seconds=5,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(10, Path(directory))
            self.assertTrue(client.export_started)
            self.assertTrue(result.archive_path.is_file())
            self.assertEqual(len(archive), result.archive_size)
            self.assertEqual(hashlib.sha256(archive).hexdigest(), result.sha256)
            self.assertFalse(list(Path(directory).glob("*.part")))
            self.assertEqual([None, 5, 5], client.request_timeouts)

    def test_waits_on_rate_limit_and_respects_retry_after(self) -> None:
        """429を一時状態として扱いRetry-After以上待機する。"""
        archive = tar_gz_bytes()
        client = ExportClient(
            [
                ApiResponse(429, {"Retry-After": "3"}, b""),
                ApiResponse(200, {}, archive),
            ]
        )
        clock = Clock()
        with tempfile.TemporaryDirectory() as directory:
            result = GroupExporter(
                client,  # type: ignore[arg-type]
                poll_interval_seconds=1,
                timeout_seconds=10,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(10, Path(directory))
        self.assertEqual(3, clock.value)
        self.assertEqual(len(archive), result.archive_size)

    def test_rejects_invalid_archive(self) -> None:
        """tar.gzでないレスポンスを保存しない。"""
        client = ExportClient([ApiResponse(200, {}, b"not-an-archive")])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ArchiveValidationError):
                GroupExporter(client, sleep=lambda _: None).export(10, Path(directory))  # type: ignore[arg-type]
            self.assertFalse(list(Path(directory).iterdir()))

    def test_times_out(self) -> None:
        """404が継続した場合は有限時間で失敗する。"""
        client = ExportClient([ApiResponse(404, {}, b"")] * 3)
        clock = Clock()
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(ExportTimeoutError),
        ):
            GroupExporter(
                client,  # type: ignore[arg-type]
                poll_interval_seconds=1,
                timeout_seconds=2,
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ).export(10, Path(directory))


if __name__ == "__main__":
    unittest.main()
