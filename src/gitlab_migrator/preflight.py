"""移行前の接続・権限・設定を非破壊で診断する。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .client import GitLabClient
from .errors import GitLabApiError


class PreflightChecker:
    """移行元と移行先が移行処理を実行できる状態か確認する。"""

    def __init__(
        self,
        source: GitLabClient,
        destination: GitLabClient,
        *,
        work_directory: Path = Path("work"),
    ) -> None:
        """診断対象を初期化する。

        Args:
            source: 移行元GitLabクライアント。
            destination: 移行先GitLabクライアント。
            work_directory: ExportとManifestを保存する作業ディレクトリ。
        """
        self.source = source
        self.destination = destination
        self.work_directory = work_directory

    def check(self) -> dict[str, Any]:
        """全診断を実行し、機械判定可能な結果を返す。

        Returns:
            `status`、`checks`、`warnings`を含む診断結果。
        """
        checks: list[dict[str, Any]] = []
        warnings: list[str] = []
        source_version = self._endpoint_checks("source", self.source, checks, warnings)
        destination_version = self._endpoint_checks(
            "destination", self.destination, checks, warnings
        )
        self._destination_settings_check(checks)
        self._work_directory_check(checks)
        if source_version and destination_version:
            warnings.extend(
                self._version_warnings(source_version, destination_version)
            )
        failed = any(item["status"] == "failed" for item in checks)
        return {
            "status": "failed" if failed else ("warning" if warnings else "passed"),
            "source_version": source_version,
            "destination_version": destination_version,
            "checks": checks,
            "warnings": warnings,
        }

    def _endpoint_checks(
        self,
        role: str,
        client: GitLabClient,
        checks: list[dict[str, Any]],
        warnings: list[str],
    ) -> str | None:
        """接続先のVersionと認証ユーザーを確認する。"""
        version: str | None = None
        try:
            payload = client.get_json("/version")
            version = str(payload.get("version", "")) if isinstance(payload, dict) else ""
            if not version:
                raise GitLabApiError("Version APIにversionがありません")
            checks.append(
                {
                    "name": f"{role}.version",
                    "status": "passed",
                    "detail": version,
                }
            )
        except GitLabApiError as exc:
            checks.append(
                {
                    "name": f"{role}.version",
                    "status": "failed",
                    "detail": str(exc),
                }
            )
        try:
            user = client.get_json("/user")
            if not isinstance(user, dict) or not user.get("username"):
                raise GitLabApiError("User APIの応答が不正です")
            checks.append(
                {
                    "name": f"{role}.authentication",
                    "status": "passed",
                    "detail": {
                        "username": user.get("username"),
                        "is_admin": bool(user.get("is_admin", False)),
                    },
                }
            )
            if not user.get("is_admin"):
                warnings.append(
                    f"{role}のTokenがAdminとして確認できません。"
                    "対象GroupのOwner権限とImport/Export権限を個別に確認してください"
                )
        except GitLabApiError as exc:
            checks.append(
                {
                    "name": f"{role}.authentication",
                    "status": "failed",
                    "detail": str(exc),
                }
            )
        parsed = urlparse(client.config.url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            warnings.append(f"{role}がHTTPSではありません: {client.config.url}")
        return version

    def _destination_settings_check(self, checks: list[dict[str, Any]]) -> None:
        """移行先でProject Import Sourceが有効か確認する。"""
        try:
            settings = self.destination.get_json("/application/settings")
            if not isinstance(settings, dict):
                raise GitLabApiError("Application Settings APIの応答が不正です")
            import_sources = settings.get("import_sources") or []
            enabled = "gitlab_project" in import_sources
            checks.append(
                {
                    "name": "destination.gitlab_project_import",
                    "status": "passed" if enabled else "failed",
                    "detail": {
                        "import_sources": import_sources,
                        "remediation": (
                            None
                            if enabled
                            else "Admin AreaでGitLab exportを有効化するか、"
                            "`gitlab-migrator enable-project-import`を明示的に実行してください"
                        ),
                    },
                }
            )
        except GitLabApiError as exc:
            checks.append(
                {
                    "name": "destination.application_settings",
                    "status": "failed",
                    "detail": (
                        f"{exc}。移行先Application Settingsを読むAdmin権限が必要です"
                    ),
                }
            )

    def _work_directory_check(self, checks: list[dict[str, Any]]) -> None:
        """作業ディレクトリの既存Parentへ書き込めるか確認する。"""
        candidate = self.work_directory
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        writable = candidate.is_dir() and os.access(candidate, os.W_OK)
        checks.append(
            {
                "name": "local.work_directory",
                "status": "passed" if writable else "failed",
                "detail": str(self.work_directory),
            }
        )

    @staticmethod
    def _version_warnings(source_version: str, destination_version: str) -> list[str]:
        """検証済みVersionとの違いを警告として返す。"""
        warnings: list[str] = []
        if not source_version.startswith("15.3.3"):
            warnings.append(
                f"移行元{source_version}は実機検証済みVersion 15.3.3と異なります"
            )
        if not destination_version.startswith("19.1.1"):
            warnings.append(
                f"移行先{destination_version}は実機検証済みVersion 19.1.1と異なります"
            )
        return warnings
