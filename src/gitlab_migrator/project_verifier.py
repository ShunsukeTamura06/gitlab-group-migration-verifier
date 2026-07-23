"""Group配下にある全Projectの配置と主要属性を比較する。"""

from __future__ import annotations

from typing import Any

from .client import GitLabClient
from .errors import GitLabApiError, HierarchyError
from .hierarchy import GroupHierarchy
from .models import GroupNode, ProjectTreeVerificationResult


class ProjectTreeVerifier:
    """内部IDとルートGroup名に依存せず全Projectを比較する。"""

    CRITICAL_FIELDS = ("name", "path", "default_branch", "empty_repo")
    WARNING_FIELDS = ("description", "visibility", "archived")

    @classmethod
    def capture(
        cls,
        client: GitLabClient,
        root_group_id: int,
        *,
        nodes: list[GroupNode] | None = None,
    ) -> dict[str, Any]:
        """Group直下を順に探索し、重複のないProject Snapshotを取得する。

        Args:
            client: Snapshot取得先GitLabクライアント。
            root_group_id: ルートGroup ID。
            nodes: 取得済みGroup階層。未指定時はAPIから取得する。

        Returns:
            相対Project Pathを含むProject Snapshot。
        """
        group_nodes = nodes or GroupHierarchy(client).fetch(root_group_id)
        roots = [node for node in group_nodes if node.relative_path == "."]
        if len(roots) != 1:
            raise HierarchyError("Project SnapshotのルートGroupを一意に特定できません")
        root_full_path = roots[0].full_path
        projects_by_id: dict[int, dict[str, Any]] = {}
        relative_paths: set[str] = set()
        for node in group_nodes:
            for summary in client.list_all(
                f"/groups/{node.id}/projects",
                params={"include_subgroups": "false", "with_shared": "false"},
            ):
                project_id = int(summary["id"])
                if project_id in projects_by_id:
                    continue
                payload = client.get_json(f"/projects/{project_id}")
                if not isinstance(payload, dict):
                    raise GitLabApiError(
                        f"Project取得APIがオブジェクト以外を返しました: {project_id}"
                    )
                full_path = str(payload.get("path_with_namespace") or "")
                prefix = f"{root_full_path}/"
                if not full_path.startswith(prefix):
                    raise HierarchyError(
                        f"Projectが指定ルート配下にありません: {full_path}"
                    )
                relative_path = full_path[len(prefix) :]
                if relative_path in relative_paths:
                    raise HierarchyError(
                        f"Projectの相対Pathが重複しています: {relative_path}"
                    )
                relative_paths.add(relative_path)
                projects_by_id[project_id] = {
                    "id": project_id,
                    "name": str(payload.get("name") or ""),
                    "path": str(payload.get("path") or ""),
                    "path_with_namespace": full_path,
                    "relative_path": relative_path,
                    "namespace_relative_path": (
                        relative_path.rsplit("/", 1)[0]
                        if "/" in relative_path
                        else "."
                    ),
                    "description": str(payload.get("description") or ""),
                    "visibility": str(payload.get("visibility") or "private"),
                    "archived": bool(payload.get("archived", False)),
                    "default_branch": payload.get("default_branch"),
                    "empty_repo": bool(
                        payload.get(
                            "empty_repo",
                            payload.get("default_branch") is None,
                        )
                    ),
                }
        projects = sorted(
            projects_by_id.values(),
            key=lambda item: item["relative_path"],
        )
        return {
            "root_group_id": root_group_id,
            "root_full_path": root_full_path,
            "project_count": len(projects),
            "projects": projects,
        }

    @classmethod
    def verify(
        cls,
        source: GitLabClient,
        destination: GitLabClient,
        source_group_id: int,
        destination_group_id: int,
    ) -> ProjectTreeVerificationResult:
        """稼働中の移行元と移行先にある全Projectを比較する。"""
        return cls.compare_snapshots(
            cls.capture(source, source_group_id),
            cls.capture(destination, destination_group_id),
        )

    @classmethod
    def compare_snapshots(
        cls,
        source_snapshot: dict[str, Any],
        destination_snapshot: dict[str, Any],
    ) -> ProjectTreeVerificationResult:
        """保存済みSnapshot同士を相対Project Pathで比較する。"""
        source = cls._index(source_snapshot, "移行元")
        destination = cls._index(destination_snapshot, "移行先")
        source_paths = set(source)
        destination_paths = set(destination)
        common_paths = sorted(source_paths & destination_paths)
        changed_projects: list[dict[str, Any]] = []
        has_critical_change = False
        for relative_path in common_paths:
            changes = {
                field: {
                    "source": source[relative_path].get(field),
                    "destination": destination[relative_path].get(field),
                }
                for field in cls.CRITICAL_FIELDS + cls.WARNING_FIELDS
                if source[relative_path].get(field)
                != destination[relative_path].get(field)
            }
            if changes:
                critical = any(field in cls.CRITICAL_FIELDS for field in changes)
                has_critical_change = has_critical_change or critical
                changed_projects.append(
                    {
                        "relative_path": relative_path,
                        "severity": "failed" if critical else "warning",
                        "changes": changes,
                    }
                )
        missing = sorted(source_paths - destination_paths)
        extra = sorted(destination_paths - source_paths)
        if missing or extra or has_critical_change:
            status = "failed"
        elif changed_projects:
            status = "warning"
        else:
            status = "success"
        return ProjectTreeVerificationResult(
            status=status,
            source_project_count=len(source),
            destination_project_count=len(destination),
            matched_project_count=len(common_paths),
            missing_projects=missing,
            extra_projects=extra,
            changed_projects=changed_projects,
        )

    @staticmethod
    def _index(snapshot: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
        """Snapshotを相対Project Pathで索引する。"""
        projects = snapshot.get("projects")
        if not isinstance(projects, list):
            raise ValueError(f"{label}Project Snapshotにprojects配列がありません")
        result: dict[str, dict[str, Any]] = {}
        for project in projects:
            if not isinstance(project, dict):
                raise ValueError(
                    f"{label}Project Snapshotの要素がオブジェクトではありません"
                )
            relative_path = str(project.get("relative_path") or "")
            if not relative_path:
                raise ValueError(f"{label}Project Snapshotにrelative_pathがありません")
            if relative_path in result:
                raise ValueError(
                    f"{label}Project Snapshotの相対Pathが重複しています: "
                    f"{relative_path}"
                )
            result[relative_path] = project
        return result
