"""個人Namespace Project一括移行のテスト。"""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from gitlab_migrator.config import GitLabConfig
from gitlab_migrator.errors import GitLabApiError
from gitlab_migrator.personal_project_migrator import (
    PersonalProjectMigrator,
    list_personal_projects,
    personal_projects_preflight,
)
from gitlab_migrator.models import ProjectExportResult, ProjectImportResult


class PersonalProjectClient:
    """個人Project APIへ固定応答を返すFakeクライアント。"""

    def __init__(
        self,
        username: str,
        projects: list[dict[str, Any]],
        *,
        existing_paths: set[str] | None = None,
    ) -> None:
        """利用者、Project、競合Pathを保持する。"""
        self.config = GitLabConfig(f"https://{username}.example", "token")
        self.username = username
        self.projects = projects
        self.existing_paths = existing_paths or set()

    @staticmethod
    def encode_id(value: object) -> str:
        """テスト用にPathをそのまま返す。"""
        return str(value)

    def list_all(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """現在ユーザーの個人Project一覧を返す。"""
        if path != "/users/1/projects":
            raise AssertionError(path)
        self.last_params = params
        return self.projects

    def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """PreflightとProject競合確認へ応答する。"""
        del params
        if path == "/version":
            return {"version": "19.1.1-ee"}
        if path == "/user":
            return {"id": 1, "username": self.username, "is_admin": False}
        if path == "/application/settings":
            raise GitLabApiError("forbidden", status=403)
        if path.startswith("/projects/"):
            full_path = path.removeprefix("/projects/")
            if full_path in self.existing_paths:
                return {"id": 99, "path_with_namespace": full_path}
            raise GitLabApiError("not found", status=404)
        raise AssertionError(path)


class PersonalProjectMigrationTest(unittest.TestCase):
    """個人Projectの列挙と事前診断を検証する。"""

    def test_lists_only_current_users_personal_projects(self) -> None:
        """Group Projectを混ぜず、個人Namespace ProjectだけをPath順で返す。"""
        client = PersonalProjectClient(
            "source-user",
            [
                {
                    "id": 2,
                    "name": "Zeta",
                    "path": "zeta",
                    "path_with_namespace": "source-user/zeta",
                },
                {
                    "id": 3,
                    "name": "Group",
                    "path": "group-project",
                    "path_with_namespace": "team/group-project",
                },
                {
                    "id": 1,
                    "name": "Alpha",
                    "path": "alpha",
                    "path_with_namespace": "source-user/alpha",
                },
            ],
        )

        projects = list_personal_projects(client)  # type: ignore[arg-type]

        self.assertEqual(["alpha", "zeta"], [item["path"] for item in projects])
        self.assertEqual("true", client.last_params["owned"])

    def test_preflight_passes_paths_and_warns_about_author_mapping(self) -> None:
        """空きPathは合格し、個人Namespaceの投稿者制約を警告する。"""
        source = PersonalProjectClient(
            "source-user",
            [
                {
                    "id": 1,
                    "name": "Alpha",
                    "path": "alpha",
                    "path_with_namespace": "source-user/alpha",
                }
            ],
        )
        destination = PersonalProjectClient("destination-user", [])

        result = personal_projects_preflight(  # type: ignore[arg-type]
            source,
            destination,
        )

        self.assertEqual("warning", result["status"])
        self.assertEqual(1, result["source_project_count"])
        self.assertTrue(
            any("後から再割り当てできません" in item for item in result["warnings"])
        )
        path_check = next(
            item
            for item in result["checks"]
            if item["name"] == "destination.personal_project_paths"
        )
        self.assertEqual("passed", path_check["status"])

    def test_preflight_fails_before_migration_when_path_exists(self) -> None:
        """移行先個人Namespaceの同名Projectを上書きしない。"""
        source = PersonalProjectClient(
            "source-user",
            [
                {
                    "id": 1,
                    "name": "Alpha",
                    "path": "alpha",
                    "path_with_namespace": "source-user/alpha",
                }
            ],
        )
        destination = PersonalProjectClient(
            "destination-user",
            [],
            existing_paths={"destination-user/alpha"},
        )

        result = personal_projects_preflight(  # type: ignore[arg-type]
            source,
            destination,
        )

        self.assertEqual("failed", result["status"])
        path_check = next(
            item
            for item in result["checks"]
            if item["name"] == "destination.personal_project_paths"
        )
        self.assertEqual(
            ["destination-user/alpha"],
            path_check["detail"]["collisions"],
        )

    def test_migrates_every_personal_project_to_destination_user(self) -> None:
        """全個人Projectを同じPathで移行先利用者直下へImportする。"""
        source = PersonalProjectClient(
            "source-user",
            [
                {
                    "id": 1,
                    "name": "Alpha",
                    "path": "alpha",
                    "path_with_namespace": "source-user/alpha",
                },
                {
                    "id": 2,
                    "name": "Beta",
                    "path": "beta",
                    "path_with_namespace": "source-user/beta",
                },
            ],
        )
        destination = PersonalProjectClient("destination-user", [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "project.tar.gz"
            archive.write_bytes(b"archive")
            exporter_result = ProjectExportResult(
                project_id=1,
                archive_path=archive,
                archive_size=7,
                sha256="a" * 64,
            )
            importer_results = [
                ProjectImportResult(
                    project_id=11,
                    full_path="destination-user/alpha",
                    response={},
                    resolved_by="response_id",
                ),
                ProjectImportResult(
                    project_id=12,
                    full_path="destination-user/beta",
                    response={},
                    resolved_by="response_id",
                ),
            ]
            with (
                patch(
                    "gitlab_migrator.personal_project_migrator.ProjectExporter"
                ) as exporter,
                patch(
                    "gitlab_migrator.personal_project_migrator.ProjectImporter"
                ) as importer,
            ):
                exporter.return_value.export.return_value = exporter_result
                importer.return_value.import_project.side_effect = importer_results
                result = PersonalProjectMigrator(  # type: ignore[arg-type]
                    source,
                    destination,
                    export_dir=root / "exports",
                    manifest_path=root / "manifest.json",
                ).migrate()

        self.assertEqual("success", result["status"])
        self.assertEqual(2, result["verification"]["matched_project_count"])
        imported_paths = [
            call.kwargs["path"]
            for call in importer.return_value.import_project.call_args_list
        ]
        self.assertEqual(["alpha", "beta"], imported_paths)
        self.assertTrue(
            all(
                call.kwargs["personal_namespace_path"] == "destination-user"
                for call in importer.return_value.import_project.call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
