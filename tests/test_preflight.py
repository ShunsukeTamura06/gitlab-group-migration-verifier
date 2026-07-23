"""移行前診断のテスト。"""

from __future__ import annotations

import unittest
from typing import Any

from gitlab_migrator.config import GitLabConfig
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
    ) -> None:
        """接続情報と応答値を保持する。"""
        self.config = GitLabConfig(url, "token")
        self.version = version
        self.is_admin = is_admin
        self.import_sources = import_sources or []

    def get_json(self, path: str) -> dict[str, Any]:
        """Version、User、Application Settingsを返す。"""
        if path == "/version":
            return {"version": self.version}
        if path == "/user":
            return {"username": "migration-admin", "is_admin": self.is_admin}
        if path == "/application/settings":
            return {"import_sources": self.import_sources}
        raise AssertionError(f"unexpected path: {path}")


class PreflightCheckerTest(unittest.TestCase):
    """必須設定と警告判定を検証する。"""

    def test_passes_validated_versions_and_import_source(self) -> None:
        """検証済みVersionとImport Sourceが揃えば成功する。"""
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
        self.assertEqual("passed", result["status"])
        self.assertEqual([], result["warnings"])

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
        """権限不足の可能性とVersion差異を警告する。"""
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
        self.assertGreaterEqual(len(result["warnings"]), 2)


if __name__ == "__main__":
    unittest.main()
