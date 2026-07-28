"""移行前の接続・権限・設定を非破壊で診断する。"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__
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
        required_free_bytes: int = 0,
    ) -> None:
        """診断対象を初期化する。

        Args:
            source: 移行元GitLabクライアント。
            destination: 移行先GitLabクライアント。
            work_directory: ExportとManifestを保存する作業ディレクトリ。
            required_free_bytes: 作業ディレクトリに必要な空き容量。
        """
        self.source = source
        self.destination = destination
        self.work_directory = work_directory
        self.required_free_bytes = required_free_bytes

    def check(
        self,
        *,
        source_group_id: int | None = None,
        destination_path: str | None = None,
        destination_parent_id: int | None = None,
    ) -> dict[str, Any]:
        """全診断を実行し、機械判定可能な結果を返す。

        Args:
            source_group_id: 移行対象Group ID。
            destination_path: 移行先で作成するGroup Path。
            destination_parent_id: 移行先Parent Group ID。

        Returns:
            `status`、`checks`、`warnings`を含む診断結果。
        """
        checks: list[dict[str, Any]] = []
        warnings: list[str] = []
        source_version = self._endpoint_checks("source", self.source, checks, warnings)
        destination_version = self._endpoint_checks(
            "destination", self.destination, checks, warnings
        )
        self._source_settings_check(checks, warnings)
        self._destination_settings_check(checks)
        self._work_directory_check(checks)
        self._migration_target_checks(
            checks,
            warnings,
            source_group_id=source_group_id,
            destination_path=destination_path,
            destination_parent_id=destination_parent_id,
        )
        if source_version and destination_version:
            warnings.extend(
                self._version_warnings(source_version, destination_version)
            )
        failed = any(item["status"] == "failed" for item in checks)
        return {
            "tool": {
                "name": "gitlab-group-migrator",
                "version": __version__,
            },
            "status": "failed" if failed else ("warning" if warnings else "passed"),
            "source_version": source_version,
            "destination_version": destination_version,
            "checks": checks,
            "warnings": warnings,
        }

    def _migration_target_checks(
        self,
        checks: list[dict[str, Any]],
        warnings: list[str],
        *,
        source_group_id: int | None,
        destination_path: str | None,
        destination_parent_id: int | None,
    ) -> None:
        """移行対象の到達性とDestination Path競合を確認する。"""
        if source_group_id is None:
            warnings.append(
                "--source-group-id未指定のため対象Groupの到達性を確認していません"
            )
        else:
            try:
                source_group = self.source.get_json(
                    f"/groups/{self.source.encode_id(source_group_id)}"
                )
                if not isinstance(source_group, dict) or not source_group.get("full_path"):
                    raise GitLabApiError("移行元Group APIの応答が不正です")
                checks.append(
                    {
                        "name": "source.group",
                        "status": "passed",
                        "detail": {
                            "id": source_group.get("id"),
                            "full_path": source_group.get("full_path"),
                        },
                    }
                )
            except GitLabApiError as exc:
                checks.append(
                    {
                        "name": "source.group",
                        "status": "failed",
                        "detail": str(exc),
                    }
                )

        if destination_path is None:
            warnings.append(
                "--destination-path未指定のため移行先Path競合を確認していません"
            )
            return
        full_path = destination_path
        if destination_parent_id is not None:
            try:
                parent = self.destination.get_json(
                    f"/groups/{self.destination.encode_id(destination_parent_id)}"
                )
                if not isinstance(parent, dict) or not parent.get("full_path"):
                    raise GitLabApiError("移行先Parent Group APIの応答が不正です")
                full_path = f"{parent['full_path']}/{destination_path}"
            except GitLabApiError as exc:
                checks.append(
                    {
                        "name": "destination.parent_group",
                        "status": "failed",
                        "detail": str(exc),
                    }
                )
                return
        try:
            existing = self.destination.get_json(
                f"/groups/{self.destination.encode_id(full_path)}"
            )
        except GitLabApiError as exc:
            if exc.status == 404:
                checks.append(
                    {
                        "name": "destination.path_available",
                        "status": "passed",
                        "detail": {"full_path": full_path},
                    }
                )
                return
            checks.append(
                {
                    "name": "destination.path_available",
                    "status": "failed",
                    "detail": str(exc),
                }
            )
            return
        checks.append(
            {
                "name": "destination.path_available",
                "status": "failed",
                "detail": {
                    "full_path": full_path,
                    "existing_group_id": (
                        existing.get("id") if isinstance(existing, dict) else None
                    ),
                    "remediation": "競合しないPathを指定してください",
                },
            }
        )

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
                        "max_import_size_mib": settings.get("max_import_size"),
                        "max_export_size_mib": settings.get("max_export_size"),
                        "max_decompressed_archive_size_mib": settings.get(
                            "max_decompressed_archive_size"
                        ),
                        "decompress_archive_file_timeout_seconds": settings.get(
                            "decompress_archive_file_timeout"
                        ),
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

    def _source_settings_check(
        self,
        checks: list[dict[str, Any]],
        warnings: list[str],
    ) -> None:
        """移行元のExport Size上限を取得する。"""
        try:
            settings = self.source.get_json("/application/settings")
            if not isinstance(settings, dict):
                raise GitLabApiError("Application Settings APIの応答が不正です")
            checks.append(
                {
                    "name": "source.export_settings",
                    "status": "passed",
                    "detail": {
                        "max_export_size_mib": settings.get("max_export_size"),
                    },
                }
            )
        except GitLabApiError:
            warnings.append(
                "sourceのApplication Settingsを取得できないため、"
                "GitLab管理者がmax_export_sizeを確認してください"
            )

    def _work_directory_check(self, checks: list[dict[str, Any]]) -> None:
        """作業ディレクトリの既存Parentへ書き込めるか確認する。"""
        candidate = self.work_directory
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        writable = candidate.is_dir() and os.access(candidate, os.W_OK)
        free_bytes = shutil.disk_usage(candidate).free if candidate.is_dir() else 0
        enough_space = (
            self.required_free_bytes <= 0 or free_bytes >= self.required_free_bytes
        )
        checks.append(
            {
                "name": "local.work_directory",
                "status": "passed" if writable and enough_space else "failed",
                "detail": {
                    "path": str(self.work_directory),
                    "free_bytes": free_bytes,
                    "required_free_bytes": self.required_free_bytes,
                },
            }
        )

    @staticmethod
    def _version_warnings(source_version: str, destination_version: str) -> list[str]:
        """検証済みVersionとの違いを警告として返す。"""
        warnings: list[str] = []
        if not PreflightChecker._officially_compatible(
            source_version,
            destination_version,
        ):
            warnings.append(
                f"{source_version}から{destination_version}へのファイルImportは、"
                "GitLab公式互換範囲（移行先から2 Minor Version以内）を超えています。"
                "実データでPilotを行い、移行責任者の承認を記録してください"
            )
        if not source_version.startswith("15.3.3"):
            warnings.append(
                f"移行元{source_version}は実機検証済みVersion 15.3.3と異なります"
            )
        if not destination_version.startswith("19.1.1"):
            warnings.append(
                f"移行先{destination_version}は実機検証済みVersion 19.1.1と異なります"
            )
        return warnings

    @staticmethod
    def _officially_compatible(
        source_version: str,
        destination_version: str,
    ) -> bool:
        """GitLab公式のファイルImport互換範囲か判定する。"""
        source_match = re.match(r"^(\d+)\.(\d+)", source_version)
        destination_match = re.match(r"^(\d+)\.(\d+)", destination_version)
        if source_match is None or destination_match is None:
            return False
        source_major, source_minor = map(int, source_match.groups())
        destination_major, destination_minor = map(int, destination_match.groups())
        distance = (
            (destination_major - source_major) * 12
            + destination_minor
            - source_minor
        )
        return 0 <= distance <= 2
