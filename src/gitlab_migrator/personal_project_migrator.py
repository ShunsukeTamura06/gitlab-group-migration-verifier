"""個人Namespace直下の全Projectを一括移行する。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .client import GitLabClient
from .errors import GitLabApiError
from .manifest import ManifestStore
from .preflight import PreflightChecker
from .project_exporter import ProjectExporter
from .project_importer import ProjectImporter


def _utcnow() -> str:
    """現在のUTC時刻をISO 8601形式で返す。"""
    return datetime.now(timezone.utc).isoformat()


def current_user(client: GitLabClient) -> dict[str, Any]:
    """Tokenに対応する現在の利用者を取得する。"""
    user = client.get_json("/user")
    if (
        not isinstance(user, dict)
        or not isinstance(user.get("id"), int)
        or not user.get("username")
    ):
        raise GitLabApiError("User APIの応答が不正です")
    return user


def list_personal_projects(client: GitLabClient) -> list[dict[str, Any]]:
    """現在の利用者の個人Namespace直下Projectを全件取得する。"""
    user = current_user(client)
    projects = client.list_all(
        f"/users/{user['id']}/projects",
        params={"order_by": "path", "sort": "asc", "owned": "true"},
    )
    username = str(user["username"])
    personal = [
        project
        for project in projects
        if isinstance(project.get("id"), int)
        and project.get("name")
        and project.get("path")
        and str(project.get("path_with_namespace") or "").startswith(f"{username}/")
    ]
    return sorted(personal, key=lambda item: str(item["path"]).casefold())


def personal_projects_preflight(
    source: GitLabClient,
    destination: GitLabClient,
    *,
    required_free_bytes: int = 0,
) -> dict[str, Any]:
    """個人Project一括移行の接続・設定・Path競合を診断する。"""
    result = PreflightChecker(
        source,
        destination,
        required_free_bytes=required_free_bytes,
    ).check(skip_migration_target_checks=True)
    checks = result["checks"]
    warnings = result["warnings"]
    projects = list_personal_projects(source)
    destination_user = current_user(destination)
    destination_username = str(destination_user["username"])
    checks.append(
        {
            "name": "source.personal_projects",
            "status": "passed" if projects else "failed",
            "detail": {
                "count": len(projects),
                "paths": [str(project["path"]) for project in projects],
            },
        }
    )
    collisions: list[str] = []
    for project in projects:
        full_path = f"{destination_username}/{project['path']}"
        try:
            destination.get_json(
                f"/projects/{destination.encode_id(full_path)}"
            )
        except GitLabApiError as exc:
            if exc.status == 404:
                continue
            checks.append(
                {
                    "name": "destination.personal_project_paths",
                    "status": "failed",
                    "detail": str(exc),
                }
            )
            break
        collisions.append(full_path)
    else:
        checks.append(
            {
                "name": "destination.personal_project_paths",
                "status": "failed" if collisions else "passed",
                "detail": {
                    "destination_username": destination_username,
                    "collisions": collisions,
                },
            }
        )
    warnings.append(
        "個人NamespaceへのImportでは投稿者マッピングを保持できません。"
        "IssueやMerge Request等の投稿者は移行先アカウントへ集約され、"
        "後から再割り当てできません"
    )
    failed = any(item["status"] == "failed" for item in checks)
    result["status"] = "failed" if failed else "warning"
    result["migration_type"] = "personal_projects"
    result["source_project_count"] = len(projects)
    result["destination_username"] = destination_username
    return result


class PersonalProjectMigrator:
    """個人Namespace直下の全Projectを同じPathで一括移行する。"""

    def __init__(
        self,
        source: GitLabClient,
        destination: GitLabClient,
        *,
        export_dir: Path,
        manifest_path: Path,
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 900.0,
    ) -> None:
        """移行に必要なClientと成果物Pathを保持する。"""
        self.source = source
        self.destination = destination
        self.export_dir = export_dir
        self.manifest_store = ManifestStore(manifest_path)
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds

    def migrate(self) -> dict[str, Any]:
        """個人Projectを全件Export・Importして結果をManifestへ保存する。"""
        source_user = current_user(self.source)
        destination_user = current_user(self.destination)
        source_projects = list_personal_projects(self.source)
        destination_username = str(destination_user["username"])
        manifest: dict[str, Any] = {
            "tool": {"name": "gitlab-group-migrator", "version": __version__},
            "migration_type": "personal_projects",
            "state": "not_started",
            "status": "running",
            "source": {
                "username": source_user["username"],
                "project_count": len(source_projects),
            },
            "destination": {"username": destination_username},
            "projects": [],
            "limitations": [
                "個人NamespaceへのImportでは投稿者が移行先アカウントへ集約され、"
                "再割り当てできません"
            ],
            "timestamps": {"started_at": _utcnow(), "finished_at": None},
        }
        self.manifest_store.save(manifest)
        try:
            for project in source_projects:
                project_id = int(project["id"])
                path = str(project["path"])
                expected_full_path = f"{destination_username}/{path}"
                export_result = ProjectExporter(
                    self.source,
                    poll_interval_seconds=self.poll_interval_seconds,
                    timeout_seconds=self.timeout_seconds,
                ).export(project_id, self.export_dir)
                item: dict[str, Any] = {
                    "source_project_id": project_id,
                    "source_path": project["path_with_namespace"],
                    "destination_path": expected_full_path,
                    "archive": export_result.to_dict(),
                    "migration_status": "export_finished",
                    "verification_status": "not_started",
                }
                manifest["projects"].append(item)
                manifest["state"] = "project_exported"
                self.manifest_store.save(manifest)
                import_result = ProjectImporter(
                    self.destination,
                    poll_interval_seconds=self.poll_interval_seconds,
                    timeout_seconds=self.timeout_seconds,
                ).import_project(
                    Path(export_result.archive_path),
                    name=str(project["name"]),
                    path=path,
                    personal_namespace_path=destination_username,
                )
                item["import"] = asdict(import_result)
                item["migration_status"] = "import_finished"
                item["verification_status"] = (
                    "success"
                    if import_result.full_path == expected_full_path
                    else "failed"
                )
                manifest["state"] = "project_imported"
                self.manifest_store.save(manifest)
            failures = [
                item
                for item in manifest["projects"]
                if item["verification_status"] != "success"
            ]
            manifest["state"] = "finished" if not failures else "failed"
            manifest["status"] = "success" if not failures else "failed"
            manifest["verification"] = {
                "status": manifest["status"],
                "source_project_count": len(source_projects),
                "destination_project_count": len(manifest["projects"]),
                "matched_project_count": len(manifest["projects"]) - len(failures),
                "failed_projects": [
                    str(item["destination_path"]) for item in failures
                ],
            }
            manifest["timestamps"]["finished_at"] = _utcnow()
            self.manifest_store.save(manifest)
            return manifest
        except Exception as exc:
            manifest["state"] = "failed"
            manifest["status"] = "failed"
            manifest["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            manifest["timestamps"]["finished_at"] = _utcnow()
            self.manifest_store.save(manifest)
            raise
