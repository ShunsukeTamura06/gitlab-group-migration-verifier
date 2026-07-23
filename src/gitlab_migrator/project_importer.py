"""最小検証用Project Import。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .client import GitLabClient
from .errors import ArchiveValidationError, ExistingGroupError, GitLabApiError
from .group_exporter import GroupExporter
from .models import ProjectImportResult


class ProjectImporter:
    """既存Projectを保護し、指定GroupへProjectをImportする。"""

    def __init__(
        self,
        client: GitLabClient,
        *,
        timeout_seconds: float = 900.0,
        poll_interval_seconds: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Project Importerを初期化する。"""
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def import_project(
        self,
        archive: Path,
        *,
        name: str,
        path: str,
        namespace_id: int,
    ) -> ProjectImportResult:
        """Projectを指定NamespaceへImportする。"""
        if not archive.is_file():
            raise ArchiveValidationError(f"Project Importアーカイブが存在しません: {archive}")
        GroupExporter._validate_archive(archive)
        namespace = self.client.get_json(f"/groups/{namespace_id}")
        if not isinstance(namespace, dict):
            raise GitLabApiError("移行先Namespace取得APIの応答が不正です")
        full_path = f"{namespace['full_path']}/{path}"
        if self._find_project(full_path):
            raise ExistingGroupError(f"移行先Projectが既に存在します: {full_path}")
        response = self.client.post_multipart(
            "/projects/import",
            {"name": name, "path": path, "namespace": namespace_id},
            file_field="file",
            file_path=archive,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitLabApiError("Project Import APIがオブジェクト以外を返しました")
        response_id = payload.get("id")
        lookup = str(response_id) if response_id is not None else full_path
        project = self._wait_for_project(lookup)
        return ProjectImportResult(
            project_id=int(project["id"]),
            full_path=str(project["path_with_namespace"]),
            response=payload,
            resolved_by="response_id" if response_id is not None else "full_path",
        )

    def _wait_for_project(self, project_id_or_path: str) -> dict[str, Any]:
        """Import後Projectが取得でき、非同期Importが完了するまで待機する。"""
        started = self._monotonic()
        while self._monotonic() - started < self.timeout_seconds:
            project = self._find_project(project_id_or_path)
            if project:
                import_status = project.get("import_status")
                if import_status in (None, "none", "finished"):
                    return project
                if import_status in {"failed", "canceled"}:
                    raise GitLabApiError(
                        f"Project Importが失敗しました: status={import_status}, "
                        f"error={project.get('import_error') or '不明'}"
                    )
            self._sleep(self.poll_interval_seconds)
        raise GitLabApiError(f"Import後Projectを確認できませんでした: {project_id_or_path}")

    def wait_for_import(self, project_id: int) -> dict[str, Any]:
        """既に開始済みのProject Import完了を待つ。"""
        return self._wait_for_project(str(project_id))

    def _find_project(self, project_id_or_path: str) -> dict[str, Any] | None:
        """ProjectをIDまたはFull Pathで取得する。"""
        try:
            payload = self.client.get_json(
                f"/projects/{self.client.encode_id(project_id_or_path)}"
            )
        except GitLabApiError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(payload, dict):
            raise GitLabApiError("Project取得APIがオブジェクト以外を返しました")
        return payload
