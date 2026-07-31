"""GitLab Project Import。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import GitLabClient
from .errors import ArchiveValidationError, ExistingGroupError, GitLabApiError
from .group_exporter import GroupExporter
from .models import ProjectImportResult


class ProjectImporter:
    """既存Projectを保護し、Groupまたは個人NamespaceへImportする。"""

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
        namespace_id: int | None = None,
        personal_namespace_path: str | None = None,
    ) -> ProjectImportResult:
        """Projectを指定Groupまたは現在利用者の個人NamespaceへImportする。"""
        if not archive.is_file():
            raise ArchiveValidationError(f"Project Importアーカイブが存在しません: {archive}")
        GroupExporter._validate_archive(archive)
        if namespace_id is not None:
            namespace = self.client.get_json(f"/groups/{namespace_id}")
            if not isinstance(namespace, dict):
                raise GitLabApiError("移行先Namespace取得APIの応答が不正です")
            namespace_path = str(namespace["full_path"])
        elif personal_namespace_path:
            namespace_path = personal_namespace_path
        else:
            raise ValueError(
                "namespace_idまたはpersonal_namespace_pathを指定してください"
            )
        full_path = f"{namespace_path}/{path}"
        if self._find_project(full_path):
            raise ExistingGroupError(f"移行先Projectが既に存在します: {full_path}")
        fields: dict[str, Any] = {"name": name, "path": path}
        if namespace_id is not None:
            fields["namespace"] = namespace_id
        response = self.client.post_multipart(
            "/projects/import",
            fields,
            file_field="file",
            file_path=archive,
            timeout_seconds=self.timeout_seconds,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitLabApiError("Project Import APIがオブジェクト以外を返しました")
        response_id = payload.get("id")
        lookup = str(response_id) if response_id is not None else full_path
        project, import_status = self._wait_for_project(lookup)
        return ProjectImportResult(
            project_id=int(project["id"]),
            full_path=str(project["path_with_namespace"]),
            response=payload,
            resolved_by="response_id" if response_id is not None else "full_path",
            failed_relations=self._failed_relations(import_status),
            correlation_id=(
                str(import_status.get("correlation_id"))
                if import_status.get("correlation_id")
                else None
            ),
        )

    def _wait_for_project(
        self,
        project_id_or_path: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Import後Projectが取得でき、非同期Importが完了するまで待機する。"""
        started = self._monotonic()
        while self._monotonic() - started < self.timeout_seconds:
            project = self._find_project(project_id_or_path)
            if project:
                project_id = int(project["id"])
                status_payload = self.client.get_json(f"/projects/{project_id}/import")
                if not isinstance(status_payload, dict):
                    raise GitLabApiError(
                        "Project Import Status APIがオブジェクト以外を返しました"
                    )
                import_status = status_payload.get("import_status")
                if import_status == "finished":
                    failed_relations = self._failed_relations(status_payload)
                    if failed_relations:
                        summary = [
                            {
                                "relation_name": item.get("relation_name"),
                                "exception_class": item.get("exception_class"),
                                "exception_message": item.get("exception_message"),
                            }
                            for item in failed_relations
                        ]
                        raise GitLabApiError(
                            "Project Importは完了しましたがRelationの一部が失敗しました: "
                            f"correlation_id="
                            f"{status_payload.get('correlation_id') or '不明'}, "
                            f"relations={json.dumps(summary, ensure_ascii=False)}"
                        )
                    return project, status_payload
                if import_status in {"failed", "canceled"}:
                    raise GitLabApiError(
                        f"Project Importが失敗しました: status={import_status}, "
                        f"error={status_payload.get('import_error') or '不明'}"
                    )
                if import_status not in {"none", "scheduled", "started"}:
                    raise GitLabApiError(
                        "Project Import Status APIが未知の状態を返しました: "
                        f"{import_status!r}"
                    )
            self._sleep(self.poll_interval_seconds)
        raise GitLabApiError(f"Import後Projectを確認できませんでした: {project_id_or_path}")

    def wait_for_import(self, project_id: int) -> dict[str, Any]:
        """既に開始済みのProject Import完了を待つ。"""
        project, import_status = self._wait_for_project(str(project_id))
        return {**project, **import_status}

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

    @staticmethod
    def _failed_relations(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Import StatusからRelation失敗の配列だけを安全に取り出す。"""
        relations = payload.get("failed_relations") or []
        if not isinstance(relations, list):
            raise GitLabApiError(
                "Project Import Status APIのfailed_relationsが配列ではありません"
            )
        return [item for item in relations if isinstance(item, dict)]
