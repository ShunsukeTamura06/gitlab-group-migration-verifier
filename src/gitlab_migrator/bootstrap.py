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
