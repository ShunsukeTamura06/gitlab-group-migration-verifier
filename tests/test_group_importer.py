"""Group Import処理のテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gitlab_migrator.client import ApiResponse
from gitlab_migrator.errors import ExistingGroupError, GitLabApiError
from gitlab_migrator.group_importer import GroupImporter
from tests.helpers import tar_gz_bytes


class ImportClient:
    """GroupImporter向けFakeクライアント。"""

    def __init__(self, existing: bool = False) -> None:
        """既存Group有無を保持する。"""
        self.existing = existing
        self.uploaded = False
        self.upload_timeout: object = None

    @staticmethod
    def encode_id(value: object) -> str:
        """テストではエンコードせず文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, object]:
        """Group存在状態を返す。"""
        if path.endswith("destination") and not self.existing:
            raise GitLabApiError("not found", status=404)
        if path.endswith("20"):
            return {"id": 20, "full_path": "destination"}
        return {"id": 20, "full_path": "destination"}

    def post_multipart(self, *_args: object, **kwargs: object) -> ApiResponse:
        """Import成功レスポンスを返す。"""
        self.uploaded = True
        self.upload_timeout = kwargs.get("timeout_seconds")
        return ApiResponse(202, {}, b'{"id":20}')


class GroupImporterTest(unittest.TestCase):
    """既存Group保護とレスポンスID解決を検証する。"""

    def setUp(self) -> None:
        """有効な一時アーカイブを作成する。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.archive = Path(self.temporary.name) / "group.tar.gz"
        self.archive.write_bytes(tar_gz_bytes())

    def tearDown(self) -> None:
        """一時ディレクトリを削除する。"""
        self.temporary.cleanup()

    def test_resolves_imported_group_by_response_id(self) -> None:
        """ImportレスポンスのIDから作成済みGroupを特定する。"""
        client = ImportClient()
        result = GroupImporter(
            client,  # type: ignore[arg-type]
            timeout_seconds=7200,
        ).import_group(
            self.archive, name="Destination", path="destination"
        )
        self.assertTrue(client.uploaded)
        self.assertEqual(7200, client.upload_timeout)
        self.assertEqual(20, result.group_id)
        self.assertEqual("response_id", result.resolved_by)

    def test_stops_when_group_exists(self) -> None:
        """既存Groupをデフォルトで上書きしない。"""
        client = ImportClient(existing=True)
        with self.assertRaises(ExistingGroupError):
            GroupImporter(client).import_group(  # type: ignore[arg-type]
                self.archive, name="Destination", path="destination"
            )
        self.assertFalse(client.uploaded)

    def test_reuses_existing_only_when_explicit(self) -> None:
        """明示指定時だけ既存Groupを再利用する。"""
        client = ImportClient(existing=True)
        result = GroupImporter(client).import_group(  # type: ignore[arg-type]
            self.archive,
            name="Destination",
            path="destination",
            reuse_existing=True,
        )
        self.assertEqual("existing_group", result.resolved_by)
        self.assertFalse(client.uploaded)


if __name__ == "__main__":
    unittest.main()
