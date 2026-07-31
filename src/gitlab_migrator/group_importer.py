"""GitLab Group ImportとImport後Groupの解決。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import GitLabClient
from .errors import ArchiveValidationError, ExistingGroupError, GitLabApiError
from .group_exporter import GroupExporter
from .models import ImportResult


class GroupImporter:
    """既存Groupを保護しながらGroup Importを実行する。"""

    def __init__(
        self,
        client: GitLabClient,
        *,
        timeout_seconds: float = 600.0,
        poll_interval_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Importerを初期化する。"""
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def import_group(
        self,
        archive: Path,
        *,
        name: str,
        path: str,
        parent_id: int | None = None,
        reuse_existing: bool = False,
    ) -> ImportResult:
        """アーカイブをImportし、作成されたGroupを特定する。

        Args:
            archive: Group Exportアーカイブ。
            name: 移行先Group名。
            path: 移行先Groupパス。
            parent_id: 移行先Parent Group ID。
            reuse_existing: 既存Groupを明示的に利用するか。

        Returns:
            Import後Groupの解決結果。

        Raises:
            ExistingGroupError: 同一Full PathのGroupが既に存在する場合。
        """
        if not archive.is_file():
            raise ArchiveValidationError(f"Importアーカイブが存在しません: {archive}")
        GroupExporter._validate_archive(archive)

        parent: dict[str, Any] | None = None
        if parent_id is not None:
            parent_payload = self.client.get_json(f"/groups/{self.client.encode_id(parent_id)}")
            if not isinstance(parent_payload, dict):
                raise GitLabApiError("Parent Group取得APIがオブジェクト以外を返しました")
            parent = parent_payload
        full_path = f"{parent['full_path']}/{path}" if parent else path
        existing = self._find_group(full_path)
        if existing:
            if not reuse_existing:
                raise ExistingGroupError(
                    f"移行先Groupが既に存在します: {full_path}。"
                    "明示的に再利用する場合は--reuse-existing-groupを指定してください"
                )
            return self._result(existing, {}, "existing_group")

        fields: dict[str, Any] = {"name": name, "path": path}
        if parent_id is not None:
            fields["parent_id"] = parent_id
        response = self.client.post_multipart(
            "/groups/import",
            fields,
            file_field="file",
            file_path=archive,
            timeout_seconds=self.timeout_seconds,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitLabApiError("Group Import APIがオブジェクト以外を返しました")

        response_id = payload.get("id") or payload.get("group_id")
        if response_id is not None:
            group = self._wait_for_group(str(response_id))
            return self._result(group, payload, "response_id")
        group = self._wait_for_group(full_path)
        return self._result(group, payload, "full_path")

    def _wait_for_group(self, group_id_or_path: str) -> dict[str, Any]:
        """Import後のGroupが取得可能になるまで待機する。"""
        started = self._monotonic()
        while self._monotonic() - started < self.timeout_seconds:
            group = self._find_group(group_id_or_path)
            if group:
                return group
            self._sleep(self.poll_interval_seconds)
        raise GitLabApiError(
            f"Import後のGroupを{self.timeout_seconds:g}秒以内に確認できませんでした: "
            f"{group_id_or_path}"
        )

    def _find_group(self, group_id_or_path: str) -> dict[str, Any] | None:
        """GroupをIDまたはFull Pathで検索し、404だけを未存在として扱う。"""
        try:
            payload = self.client.get_json(
                f"/groups/{self.client.encode_id(group_id_or_path)}"
            )
        except GitLabApiError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(payload, dict):
            raise GitLabApiError("Group取得APIがオブジェクト以外を返しました")
        return payload

    @staticmethod
    def _result(group: dict[str, Any], response: dict[str, Any], resolved_by: str) -> ImportResult:
        """API payloadからImportResultを生成する。"""
        return ImportResult(
            group_id=int(group["id"]),
            full_path=str(group["full_path"]),
            response=response,
            resolved_by=resolved_by,
        )
