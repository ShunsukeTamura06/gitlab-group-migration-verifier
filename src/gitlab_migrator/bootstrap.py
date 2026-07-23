"""最小実機検証用Groupデータの作成。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .client import GitLabClient
from .errors import ExistingGroupError, GitLabApiError


class MinimalGroupBootstrapper:
    """仕様19のGroup、Subgroup、Label、Milestoneを作成する。"""

    def __init__(self, client: GitLabClient) -> None:
        """Bootstrapperを初期化する。"""
        self.client = client

    def create(self, *, name: str, path: str) -> dict[str, Any]:
        """破壊的な上書きをせず最小テストデータを作成する。

        Args:
            name: トップレベルGroup名。
            path: トップレベルGroupパス。

        Returns:
            作成したリソースのIDとFull Path。
        """
        existing = self._find_group(path)
        if existing:
            raise ExistingGroupError(f"テスト用Groupが既に存在します: {path}")
        root = self.client.post_form(
            "/groups",
            {
                "name": name,
                "path": path,
                "description": "GitLab 15.3.3 → 19.1.1 最小移行検証 🚚\n**Markdown**",
                "visibility": "private",
            },
            expected={201},
        ).json()
        if not isinstance(root, dict) or "id" not in root:
            raise GitLabApiError("テスト用トップレベルGroupの作成結果が不正です")
        root_id = int(root["id"])
        subgroup = self.client.post_form(
            "/groups",
            {
                "name": "日本語サブグループ",
                "path": "subgroup",
                "parent_id": root_id,
                "description": "空のサブグループ（階層維持確認用）",
                "visibility": "private",
            },
            expected={201},
        ).json()
        label = self.client.post_form(
            f"/groups/{root_id}/labels",
            {
                "name": "移行検証::重要 🚨",
                "color": "#D9534F",
                "description": "特殊文字・Unicodeを含むラベル",
            },
            expected={201},
        ).json()
        today = date.today()
        milestone = self.client.post_form(
            f"/groups/{root_id}/milestones",
            {
                "title": "移行検証マイルストーン",
                "description": "Group Export/Import比較用",
                "start_date": today.isoformat(),
                "due_date": (today + timedelta(days=30)).isoformat(),
            },
            expected={201},
        ).json()
        return {
            "root": self._summary(root),
            "subgroup": self._summary(subgroup),
            "label": self._summary(label),
            "milestone": self._summary(milestone),
        }

    def _find_group(self, full_path: str) -> dict[str, Any] | None:
        """GroupをFull Pathで検索する。"""
        try:
            payload = self.client.get_json(f"/groups/{self.client.encode_id(full_path)}")
        except GitLabApiError as exc:
            if exc.status == 404:
                return None
            raise
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _summary(payload: Any) -> dict[str, Any]:
        """APIレスポンスから必要な識別情報だけを抽出する。"""
        if not isinstance(payload, dict):
            raise GitLabApiError("作成APIがオブジェクト以外を返しました")
        return {
            key: payload[key]
            for key in ("id", "name", "title", "path", "full_path")
            if key in payload
        }


class FullTreeBootstrapper(MinimalGroupBootstrapper):
    """複数階層と全Project一括移行用の完全なテストツリーを作成する。"""

    GROUPS = (
        ("platform", "platform", "Platform", ".", "public"),
        ("backend", "backend", "Backend", "platform", "private"),
        ("frontend", "frontend", "Frontend", "platform", "public"),
        ("data", "data", "Data", ".", "internal"),
        ("analytics", "analytics", "Analytics", "data", "private"),
        ("japanese", "japanese-group", "日本語グループ", ".", "public"),
        ("empty", "empty-subgroup", "empty-subgroup", ".", "private"),
    )
    PROJECTS = (
        ("api-service", "api-service", "backend", "private"),
        ("batch-service", "batch-service", "backend", "private"),
        ("web-application", "web-application", "frontend", "public"),
        ("analytics-engine", "analytics-engine", "analytics", "private"),
        ("data-pipeline", "data-pipeline", "data", "internal"),
        ("japanese-project", "日本語プロジェクト", "japanese", "public"),
        ("root-project", "root-project", ".", "public"),
    )

    def create(self, *, name: str, path: str) -> dict[str, Any]:
        """仕様3章のGroup階層と7 Projectを破壊せず作成する。

        Args:
            name: トップレベルGroup名。
            path: トップレベルGroupパス。

        Returns:
            作成したGroupとProjectの識別情報。
        """
        if self._find_group(path):
            raise ExistingGroupError(f"テスト用Groupが既に存在します: {path}")
        root = self._create_group(
            name=name,
            path=path,
            parent_id=None,
            description="全Project一括移行検証ルート 🚚\n**full tree**",
            visibility="public",
        )
        group_ids: dict[str, int] = {".": int(root["id"])}
        groups: list[dict[str, Any]] = [self._summary(root)]
        for key, group_path, group_name, parent_key, visibility in self.GROUPS:
            group = self._create_group(
                name=group_name,
                path=group_path,
                parent_id=group_ids[parent_key],
                description=f"全Project一括移行検証: {group_name}",
                visibility=visibility,
            )
            group_ids[key] = int(group["id"])
            groups.append(self._summary(group))

        projects: list[dict[str, Any]] = []
        for project_path, project_name, group_key, visibility in self.PROJECTS:
            project = self.client.post_form(
                "/projects",
                {
                    "name": project_name,
                    "path": project_path,
                    "namespace_id": group_ids[group_key],
                    "initialize_with_readme": "true",
                    "description": f"一括移行検証Project: {project_name}",
                    "visibility": visibility,
                },
                expected={201},
            ).json()
            if not isinstance(project, dict) or "id" not in project:
                raise GitLabApiError(
                    f"テスト用Projectの作成結果が不正です: {project_path}"
                )
            projects.append(
                {
                    key: project.get(key)
                    for key in (
                        "id",
                        "name",
                        "path",
                        "path_with_namespace",
                        "default_branch",
                        "visibility",
                    )
                }
            )
        return {
            "root": self._summary(root),
            "groups": groups,
            "projects": projects,
            "group_count": len(groups),
            "project_count": len(projects),
        }

    def _create_group(
        self,
        *,
        name: str,
        path: str,
        parent_id: int | None,
        description: str,
        visibility: str,
    ) -> dict[str, Any]:
        """Groupを作成しAPI応答を検証する。"""
        fields: dict[str, Any] = {
            "name": name,
            "path": path,
            "description": description,
            "visibility": visibility,
        }
        if parent_id is not None:
            fields["parent_id"] = parent_id
        payload = self.client.post_form(
            "/groups",
            fields,
            expected={201},
        ).json()
        if not isinstance(payload, dict) or "id" not in payload:
            raise GitLabApiError(f"テスト用Groupの作成結果が不正です: {path}")
        return payload
