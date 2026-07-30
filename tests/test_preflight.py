"""移行前診断のテスト。"""

from __future__ import annotations

import unittest
from typing import Any

from gitlab_migrator.config import GitLabConfig
from gitlab_migrator.errors import GitLabApiError
from gitlab_migrator.preflight import PreflightChecker


class PreflightClient:
    """Preflight APIへ固定レスポンスを返すFakeクライアント。"""

    def __init__(
        self,
        url: str,
        version: str,
        *,
        is_admin: bool = True,
        import_sources: list[str] | None = None,
        groups: dict[str, dict[str, Any]] | None = None,
        application_settings_error: GitLabApiError | None = None,
    ) -> None:
        """接続情報と応答値を保持する。"""
        self.config = GitLabConfig(url, "token")
        self.version = version
        self.is_admin = is_admin
        self.import_sources = import_sources or []
        self.groups = groups or {}
        self.application_settings_error = application_settings_error

    @staticmethod
    def encode_id(value: object) -> str:
        """テスト用Group IDを文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, Any]:
        """Version、User、Application Settingsを返す。"""
        if path == "/version":
            return {"version": self.version}
        if path == "/user":
            return {"username": "migration-admin", "is_admin": self.is_admin}
        if path == "/application/settings":
            if self.application_settings_error is not None:
                raise self.application_settings_error
            return {
                "import_sources": self.import_sources,
                "max_import_size": 5120,
                "max_export_size": 0,
                "max_decompressed_archive_size": 25600,
                "decompress_archive_file_timeout": 210,
            }
        if path.startswith("/groups/"):
            group_id_or_path = path.removeprefix("/groups/")
            if group_id_or_path in self.groups:
                return self.groups[group_id_or_path]
            raise GitLabApiError("not found", status=404)
        raise AssertionError(f"unexpected path: {path}")


class PreflightCheckerTest(unittest.TestCase):
    """必須設定と警告判定を検証する。"""

    def test_warns_when_validated_versions_exceed_official_compatibility(self) -> None:
        """実機検証済みでも公式の2 Minor Version範囲外なら警告する。"""
        result = PreflightChecker(
            PreflightClient(  # type: ignore[arg-type]
                "https://source.example",
                "15.3.3-ee",
            ),
            PreflightClient(  # type: ignore[arg-type]
                "https://destination.example",
                "19.1.1-ee",
                import_sources=["gitlab_project"],
            ),
        ).check()
        self.assertEqual("warning", result["status"])
        self.assertTrue(
            any("公式互換範囲" in warning for warning in result["warnings"])
        )
        settings_check = next(
            item
            for item in result["checks"]
            if item["name"] == "destination.gitlab_project_import"
        )
        self.assertEqual(5120, settings_check["detail"]["max_import_size_mib"])

    def test_fails_when_project_import_source_is_disabled(self) -> None:
        """Project Import Source未設定は移行前に失敗とする。"""
        result = PreflightChecker(
            PreflightClient(  # type: ignore[arg-type]
                "https://source.example",
                "15.3.3-ee",
            ),
            PreflightClient(  # type: ignore[arg-type]
                "https://destination.example",
                "19.1.1-ee",
            ),
        ).check()
        self.assertEqual("failed", result["status"])
        failed_names = {
            item["name"] for item in result["checks"] if item["status"] == "failed"
        }
        self.assertIn("destination.gitlab_project_import", failed_names)

    def test_warns_for_non_admin_and_unvalidated_version(self) -> None:
        """一般利用者TokenでもAdmin権限不足だけでは警告しない。"""
        result = PreflightChecker(
            PreflightClient(  # type: ignore[arg-type]
                "https://source.example",
                "16.11.0-ee",
                is_admin=False,
            ),
            PreflightClient(  # type: ignore[arg-type]
                "https://destination.example",
                "19.1.1-ee",
                import_sources=["gitlab_project"],
            ),
        ).check()
        self.assertEqual("warning", result["status"])
        self.assertFalse(
            any("Adminとして確認できません" in warning for warning in result["warnings"])
        )

    def test_skips_destination_application_settings_for_non_admin(self) -> None:
        """管理者専用設定の403は警告に留め、移行を妨げない。"""
        result = PreflightChecker(
            PreflightClient(  # type: ignore[arg-type]
                "https://source.example",
                "19.1.1-ee",
            ),
            PreflightClient(  # type: ignore[arg-type]
                "https://destination.example",
                "19.1.1-ee",
                is_admin=False,
                application_settings_error=GitLabApiError(
                    "GitLab API HTTP 403",
                    status=403,
                ),
            ),
        ).check()

        self.assertEqual("warning", result["status"])
        settings_check = next(
            item
            for item in result["checks"]
            if item["name"] == "destination.application_settings"
        )
        self.assertEqual("skipped", settings_check["status"])
        self.assertEqual(403, settings_check["detail"]["http_status"])
        self.assertTrue(
            any("管理者Tokenを渡す必要はありません" in warning for warning in result["warnings"])
        )

    def test_checks_source_group_and_destination_path_collision(self) -> None:
        """対象Groupの到達性と移行先Pathの競合を事前検出する。"""
        source = PreflightClient(
            "https://source.example",
            "15.3.3-ee",
            groups={"123": {"id": 123, "full_path": "legacy/engineering"}},
        )
        destination = PreflightClient(
            "https://destination.example",
            "19.1.1-ee",
            import_sources=["gitlab_project"],
            groups={"engineering": {"id": 456, "full_path": "engineering"}},
        )

        result = PreflightChecker(  # type: ignore[arg-type]
            source,
            destination,
        ).check(
            source_group_id=123,
            destination_path="engineering",
        )

        failed_names = {
            item["name"] for item in result["checks"] if item["status"] == "failed"
        }
        self.assertIn("destination.path_available", failed_names)
        source_check = next(
            item for item in result["checks"] if item["name"] == "source.group"
        )
        self.assertEqual("legacy/engineering", source_check["detail"]["full_path"])

    def test_fails_when_required_disk_space_is_not_available(self) -> None:
        """指定した必要容量を確保できなければ事前診断を失敗にする。"""
        result = PreflightChecker(
            PreflightClient(  # type: ignore[arg-type]
                "https://source.example",
                "15.3.3-ee",
            ),
            PreflightClient(  # type: ignore[arg-type]
                "https://destination.example",
                "19.1.1-ee",
                import_sources=["gitlab_project"],
            ),
            required_free_bytes=10**30,
        ).check()

        work_directory_check = next(
            item
            for item in result["checks"]
            if item["name"] == "local.work_directory"
        )
        self.assertEqual("failed", work_directory_check["status"])

    def test_official_compatibility_handles_major_version_boundary(self) -> None:
        """Major境界をまたぐ2 Minor Version以内を互換範囲とする。"""
        self.assertTrue(
            PreflightChecker._officially_compatible("18.11.4-ee", "19.1.0-ee")
        )
        self.assertFalse(
            PreflightChecker._officially_compatible("18.10.4-ee", "19.1.0-ee")
        )


if __name__ == "__main__":
    unittest.main()
