"""個人Namespace直下の全Projectを一括移行する。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .client import GitLabClient
from .errors import ExistingGroupError, GitLabApiError, MigratorError
from .group_exporter import GroupExporter
from .manifest import ManifestStore
from .preflight import PreflightChecker
from .project_exporter import ProjectExporter
from .project_importer import ProjectImporter


def _utcnow() -> str:
    """現在のUTC時刻をISO 8601形式で返す。"""
    return datetime.now(UTC).isoformat()


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
                "status": "warning" if collisions else "passed",
                "detail": {
                    "destination_username": destination_username,
                    "collisions": collisions,
                    "behavior": "skip_existing",
                },
            }
        )
    if collisions:
        warnings.append(
            f"移行先に同じPathのProjectが{len(collisions)}件あります。"
            "既存Projectは上書き・内容比較せずスキップし、"
            "残りのProjectだけを移行します: "
            + ", ".join(collisions)
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
    result["collision_count"] = len(collisions)
    result["collisions"] = collisions
    result["migration_candidate_count"] = len(projects) - len(collisions)
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
                "projects": [
                    {
                        "id": int(project["id"]),
                        "path": str(project["path"]),
                        "path_with_namespace": str(project["path_with_namespace"]),
                    }
                    for project in source_projects
                ],
            },
            "destination": {"username": destination_username},
            "projects": [],
            "limitations": [
                (
                    "個人NamespaceへのImportでは投稿者が移行先アカウントへ集約され、"
                    "再割り当てできません"
                ),
            ],
            "timestamps": {"started_at": _utcnow(), "finished_at": None},
        }
        self.manifest_store.save(manifest)
        return self._continue_migration(
            manifest,
            source_projects,
            destination_username=destination_username,
        )

    def resume(self) -> dict[str, Any]:
        """失敗または中断した個人Project移行をManifestから再開する。"""
        manifest = self.manifest_store.load()
        source_user = current_user(self.source)
        destination_user = current_user(self.destination)
        source_projects = list_personal_projects(self.source)
        destination_username = str(destination_user["username"])
        self._validate_resume(
            manifest,
            source_projects,
            source_username=str(source_user["username"]),
            destination_username=destination_username,
        )
        timestamps = manifest.setdefault("timestamps", {})
        resumed_at = timestamps.setdefault("resumed_at", [])
        if not isinstance(resumed_at, list):
            raise MigratorError("Manifestのresumed_atが配列ではありません")
        resumed_at.append(_utcnow())
        timestamps["finished_at"] = None
        manifest["state"] = "resuming"
        manifest["status"] = "running"
        manifest["resumed_with_version"] = __version__
        manifest.pop("error", None)
        self.manifest_store.save(manifest)
        return self._continue_migration(
            manifest,
            source_projects,
            destination_username=destination_username,
        )

    def _continue_migration(
        self,
        manifest: dict[str, Any],
        source_projects: list[dict[str, Any]],
        *,
        destination_username: str,
    ) -> dict[str, Any]:
        """未処理ProjectだけをExport・ImportしてManifestを完成させる。"""
        try:
            records = manifest.get("projects")
            if not isinstance(records, list):
                raise MigratorError("Manifestのprojectsが配列ではありません")
            records_by_id = {
                int(item["source_project_id"]): item
                for item in records
                if isinstance(item, dict)
                and isinstance(item.get("source_project_id"), int)
            }
            for project in source_projects:
                project_id = int(project["id"])
                path = str(project["path"])
                expected_full_path = f"{destination_username}/{path}"
                item = records_by_id.get(project_id)
                may_have_started_import = (
                    item is not None
                    and item.get("migration_status")
                    in {"export_finished", "import_started"}
                )
                if item is not None:
                    if item.get("verification_status") == "success":
                        self._verify_completed_project(item, expected_full_path)
                        continue
                    if item.get("migration_status") == "skipped_existing":
                        existing_project = self._find_destination_project(
                            expected_full_path
                        )
                        if existing_project is not None:
                            continue
                else:
                    item = {
                        "source_project_id": project_id,
                        "source_path": project["path_with_namespace"],
                        "destination_path": expected_full_path,
                        "migration_status": "not_started",
                        "verification_status": "not_started",
                    }
                    records.append(item)
                    records_by_id[project_id] = item
                    self.manifest_store.save(manifest)

                existing_project = self._find_destination_project(expected_full_path)
                if existing_project is not None:
                    if may_have_started_import:
                        self._finish_started_import(
                            item,
                            existing_project,
                            expected_full_path=expected_full_path,
                        )
                        manifest["state"] = "project_imported"
                    else:
                        self._mark_existing_skipped(item, existing_project)
                        manifest["state"] = "project_skipped"
                    self.manifest_store.save(manifest)
                    continue

                archive_path = self._validated_existing_archive(item)
                if archive_path is None:
                    item["migration_status"] = "export_started"
                    manifest["state"] = "project_export_started"
                    self.manifest_store.save(manifest)
                    export_result = ProjectExporter(
                        self.source,
                        poll_interval_seconds=self.poll_interval_seconds,
                        timeout_seconds=self.timeout_seconds,
                    ).export(project_id, self.export_dir)
                    item["archive"] = export_result.to_dict()
                    item["migration_status"] = "export_finished"
                    manifest["state"] = "project_exported"
                    self.manifest_store.save(manifest)
                    archive_path = Path(export_result.archive_path)

                item["migration_status"] = "import_started"
                manifest["state"] = "project_import_started"
                self.manifest_store.save(manifest)
                try:
                    import_result = ProjectImporter(
                        self.destination,
                        poll_interval_seconds=self.poll_interval_seconds,
                        timeout_seconds=self.timeout_seconds,
                    ).import_project(
                        archive_path,
                        name=str(project["name"]),
                        path=path,
                        personal_namespace_path=destination_username,
                    )
                except ExistingGroupError:
                    existing_project = self._find_destination_project(
                        expected_full_path
                    )
                    if existing_project is None:
                        raise
                    self._mark_existing_skipped(item, existing_project)
                    manifest["state"] = "project_skipped"
                    self.manifest_store.save(manifest)
                    continue
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
                if item["verification_status"] not in {"success", "skipped"}
            ]
            imported = [
                item
                for item in manifest["projects"]
                if item["verification_status"] == "success"
            ]
            skipped = [
                item
                for item in manifest["projects"]
                if item["verification_status"] == "skipped"
            ]
            manifest["state"] = "finished" if not failures else "failed"
            if failures:
                manifest["status"] = "failed"
            elif skipped:
                manifest["status"] = "warning"
            else:
                manifest["status"] = "success"
            manifest["verification"] = {
                "status": manifest["status"],
                "source_project_count": len(source_projects),
                "destination_project_count": len(imported) + len(skipped),
                "matched_project_count": len(imported),
                "imported_project_count": len(imported),
                "skipped_project_count": len(skipped),
                "skipped_projects": [
                    str(item["destination_path"]) for item in skipped
                ],
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

    def _validate_resume(
        self,
        manifest: dict[str, Any],
        source_projects: list[dict[str, Any]],
        *,
        source_username: str,
        destination_username: str,
    ) -> None:
        """Manifestと現在のToken・移行対象が同一であることを検証する。"""
        if manifest.get("migration_type") != "personal_projects":
            raise MigratorError("個人Project移行のManifestではありません")
        if manifest.get("status") == "success":
            raise MigratorError("この個人Project移行は既に完了しています")
        source = manifest.get("source")
        destination = manifest.get("destination")
        if not isinstance(source, dict) or not isinstance(destination, dict):
            raise MigratorError("ManifestのSourceまたはDestination情報が不正です")
        if str(source.get("username")) != source_username:
            raise MigratorError(
                "移行元TokenのアカウントがManifestと一致しません: "
                f"expected={source.get('username')}, actual={source_username}"
            )
        if str(destination.get("username")) != destination_username:
            raise MigratorError(
                "移行先TokenのアカウントがManifestと一致しません: "
                f"expected={destination.get('username')}, actual={destination_username}"
            )
        if source.get("project_count") != len(source_projects):
            raise MigratorError(
                "移行元の個人Project数が開始時から変わっています。"
                "追加・削除を確認してから再開してください"
            )
        current_by_id = {int(project["id"]): project for project in source_projects}
        records = manifest.get("projects")
        if not isinstance(records, list):
            raise MigratorError("Manifestのprojectsが配列ではありません")
        seen: set[int] = set()
        for item in records:
            if not isinstance(item, dict) or not isinstance(
                item.get("source_project_id"), int
            ):
                raise MigratorError("ManifestのProject記録が不正です")
            project_id = int(item["source_project_id"])
            if project_id in seen:
                raise MigratorError(
                    f"ManifestにProject IDが重複しています: {project_id}"
                )
            seen.add(project_id)
            current = current_by_id.get(project_id)
            if current is None or str(current["path_with_namespace"]) != str(
                item.get("source_path")
            ):
                raise MigratorError(
                    f"移行元Projectが開始時から変わっています: {project_id}"
                )
            expected_destination = f"{destination_username}/{current['path']}"
            if str(item.get("destination_path")) != expected_destination:
                raise MigratorError(
                    "Manifestの移行先Pathが現在のアカウントと一致しません: "
                    f"{item.get('destination_path')}"
                )

    def _validated_existing_archive(self, item: dict[str, Any]) -> Path | None:
        """Manifestに保存済みのArchiveがあれば完全性を検証して返す。"""
        archive = item.get("archive")
        if not isinstance(archive, dict) or not archive.get("archive_path"):
            return None
        stored_path = Path(str(archive["archive_path"]))
        archive_path = (
            stored_path
            if stored_path.is_file()
            else self.export_dir / stored_path.name
        )
        if not archive_path.is_file():
            return None
        GroupExporter._validate_archive(archive_path)
        expected_sha256 = str(archive.get("sha256") or "")
        actual_sha256 = GroupExporter._sha256(archive_path)
        if not expected_sha256 or actual_sha256 != expected_sha256:
            raise MigratorError(
                f"保存済みProject ArchiveのSHA-256が一致しません: {archive_path}"
            )
        return archive_path

    def _find_destination_project(self, full_path: str) -> dict[str, Any] | None:
        """移行先のProjectをFull Pathで検索する。"""
        try:
            project = self.destination.get_json(
                f"/projects/{self.destination.encode_id(full_path)}"
            )
        except GitLabApiError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(project, dict) or not isinstance(project.get("id"), int):
            raise MigratorError("移行先Project取得APIの応答が不正です")
        return project

    @staticmethod
    def _mark_existing_skipped(
        item: dict[str, Any],
        existing_project: dict[str, Any],
    ) -> None:
        """既存の移行先Projectを上書きせずスキップとして記録する。"""
        item["migration_status"] = "skipped_existing"
        item["verification_status"] = "skipped"
        item["skip_reason"] = "destination_path_exists"
        item["destination_project_id"] = int(existing_project["id"])

    def _verify_completed_project(
        self,
        item: dict[str, Any],
        expected_full_path: str,
    ) -> None:
        """完了済み記録の移行先Projectが残っていることを確認する。"""
        project = self._find_destination_project(expected_full_path)
        if project is None:
            raise MigratorError(
                "完了済みProjectが移行先にありません。自動再作成は行いません: "
                f"{expected_full_path}"
            )
        if str(project.get("path_with_namespace")) != expected_full_path:
            raise MigratorError(
                f"完了済みProjectのPathが一致しません: {expected_full_path}"
            )

    def _finish_started_import(
        self,
        item: dict[str, Any],
        project: dict[str, Any],
        *,
        expected_full_path: str,
    ) -> None:
        """開始済みImportの完了を確認し、既存Projectを重複Importしない。"""
        if item.get("migration_status") not in {
            "export_finished",
            "import_started",
        }:
            raise MigratorError(
                "移行先に同名Projectがありますが、このManifestでImportを"
                f"開始した記録がありません: {expected_full_path}"
            )
        completed = ProjectImporter(
            self.destination,
            poll_interval_seconds=self.poll_interval_seconds,
            timeout_seconds=self.timeout_seconds,
        ).wait_for_import(int(project["id"]))
        actual_full_path = str(completed.get("path_with_namespace") or "")
        if actual_full_path != expected_full_path:
            raise MigratorError(
                "開始済みImportの移行先Pathが一致しません: "
                f"expected={expected_full_path}, actual={actual_full_path}"
            )
        item["import"] = {
            "project_id": int(project["id"]),
            "full_path": actual_full_path,
            "resolved_by": "resume_existing_project",
            "failed_relations": completed.get("failed_relations") or [],
            "correlation_id": completed.get("correlation_id"),
            "status": "finished",
        }
        item["migration_status"] = "import_finished"
        item["verification_status"] = "success"
