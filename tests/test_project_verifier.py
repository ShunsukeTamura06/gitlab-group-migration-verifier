"""Group配下の全Project比較テスト。"""

from __future__ import annotations

import unittest
from typing import Any

from gitlab_migrator.project_verifier import ProjectTreeVerifier


class ProjectTreeClient:
    """複数階層と複数Projectを返すFakeクライアント。"""

    def __init__(
        self,
        root_id: int,
        root_path: str,
        *,
        id_offset: int = 0,
        omit_relative_path: str | None = None,
        visibility_override: str | None = None,
    ) -> None:
        """Group、Project IDと差分条件を保持する。"""
        self.root_id = root_id
        self.root_path = root_path
        self.id_offset = id_offset
        self.omit_relative_path = omit_relative_path
        self.visibility_override = visibility_override

    @staticmethod
    def encode_id(value: object) -> str:
        """IDを文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, Any]:
        """GroupまたはProject詳細を返す。"""
        item_id = int(path.rsplit("/", 1)[1])
        if path.startswith("/groups/"):
            return self._groups()[item_id]
        return next(
            project
            for project in self._projects()
            if int(project["id"]) == item_id
        )

    def list_all(
        self,
        path: str,
        **_kwargs: object,
    ) -> list[dict[str, Any]]:
        """直下Subgroupまたは直下Projectを返す。"""
        group_id = int(path.split("/")[2])
        if path.endswith("/subgroups"):
            return [
                group
                for group in self._groups().values()
                if group.get("parent_id") == group_id
            ]
        return [
            project
            for project in self._projects()
            if int(project["namespace"]["id"]) == group_id
        ]

    def _groups(self) -> dict[int, dict[str, Any]]:
        """3階層のGroup情報を生成する。"""
        root = self.root_id
        return {
            root: {
                "id": root,
                "name": self.root_path,
                "path": self.root_path,
                "full_path": self.root_path,
                "parent_id": None,
                "visibility": "private",
            },
            root + 1: {
                "id": root + 1,
                "name": "platform",
                "path": "platform",
                "full_path": f"{self.root_path}/platform",
                "parent_id": root,
                "visibility": "private",
            },
            root + 2: {
                "id": root + 2,
                "name": "backend",
                "path": "backend",
                "full_path": f"{self.root_path}/platform/backend",
                "parent_id": root + 1,
                "visibility": "private",
            },
        }

    def _projects(self) -> list[dict[str, Any]]:
        """異なる階層にある3 Projectを生成する。"""
        definitions = [
            ("root-project", self.root_id),
            ("web-application", self.root_id + 1),
            ("api-service", self.root_id + 2),
        ]
        projects = []
        for index, (project_path, namespace_id) in enumerate(definitions, start=1):
            namespace = self._groups()[namespace_id]
            full_path = f"{namespace['full_path']}/{project_path}"
            relative_path = full_path[len(self.root_path) + 1 :]
            if relative_path == self.omit_relative_path:
                continue
            projects.append(
                {
                    "id": self.id_offset + index,
                    "name": project_path,
                    "path": project_path,
                    "path_with_namespace": full_path,
                    "namespace": {"id": namespace_id},
                    "description": f"description:{project_path}",
                    "visibility": (
                        self.visibility_override
                        if self.visibility_override and project_path == "api-service"
                        else "private"
                    ),
                    "archived": False,
                    "default_branch": "main",
                    "empty_repo": False,
                }
            )
        return projects


class ProjectTreeVerifierTest(unittest.TestCase):
    """全Projectの列挙、配置、属性差分を検証する。"""

    def test_matches_all_projects_across_nested_namespaces(self) -> None:
        """ルート名と内部IDが変わっても全Projectが一致する。"""
        source = ProjectTreeVerifier.capture(
            ProjectTreeClient(10, "source"),  # type: ignore[arg-type]
            10,
        )
        destination = ProjectTreeVerifier.capture(
            ProjectTreeClient(100, "destination", id_offset=1000),  # type: ignore[arg-type]
            100,
        )
        result = ProjectTreeVerifier.compare_snapshots(source, destination)
        self.assertEqual("success", result.status)
        self.assertEqual(3, result.source_project_count)
        self.assertEqual(3, result.matched_project_count)
        self.assertEqual([], result.missing_projects)

    def test_fails_when_nested_project_is_missing(self) -> None:
        """サブグループ配下のProject欠落を重大失敗にする。"""
        source = ProjectTreeVerifier.capture(
            ProjectTreeClient(10, "source"),  # type: ignore[arg-type]
            10,
        )
        destination = ProjectTreeVerifier.capture(
            ProjectTreeClient(  # type: ignore[arg-type]
                100,
                "destination",
                id_offset=1000,
                omit_relative_path="platform/backend/api-service",
            ),
            100,
        )
        result = ProjectTreeVerifier.compare_snapshots(source, destination)
        self.assertEqual("failed", result.status)
        self.assertEqual(
            ["platform/backend/api-service"],
            result.missing_projects,
        )

    def test_warns_when_visibility_changes(self) -> None:
        """配置が正しくVisibilityだけ変わった場合は警告にする。"""
        source = ProjectTreeVerifier.capture(
            ProjectTreeClient(10, "source"),  # type: ignore[arg-type]
            10,
        )
        destination = ProjectTreeVerifier.capture(
            ProjectTreeClient(  # type: ignore[arg-type]
                100,
                "destination",
                id_offset=1000,
                visibility_override="internal",
            ),
            100,
        )
        result = ProjectTreeVerifier.compare_snapshots(source, destination)
        self.assertEqual("warning", result.status)
        self.assertEqual("warning", result.changed_projects[0]["severity"])


if __name__ == "__main__":
    unittest.main()
