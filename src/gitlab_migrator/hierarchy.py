"""GitLab Group階層の取得と検証。"""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

from .client import GitLabClient
from .errors import GitLabApiError, HierarchyError
from .models import GroupNode


class GroupHierarchy:
    """Groupツリーを重複なく取得する。"""

    def __init__(self, client: GitLabClient) -> None:
        """階層取得サービスを初期化する。"""
        self.client = client

    def fetch(
        self,
        root_group_id: int,
        *,
        order: Literal["breadth_first", "depth_first"] = "breadth_first",
    ) -> list[GroupNode]:
        """ルートGroup以下の全Groupを移行順で取得する。

        Args:
            root_group_id: ルートGroup ID。
            order: 幅優先または深さ優先。

        Returns:
            ルートを先頭とするGroupノード一覧。
        """
        root_payload = self.client.get_json(f"/groups/{self.client.encode_id(root_group_id)}")
        if not isinstance(root_payload, dict):
            raise GitLabApiError("Group取得APIがオブジェクト以外を返しました")
        root_full_path = str(root_payload["full_path"])
        root = self._to_node(root_payload, root_full_path, depth=0)
        pending: deque[GroupNode] = deque([root])
        nodes: list[GroupNode] = []
        seen_ids: set[int] = set()
        seen_paths: set[str] = set()

        while pending:
            current = pending.popleft() if order == "breadth_first" else pending.pop()
            if current.id in seen_ids:
                raise HierarchyError(f"Group階層に循環または重複IDがあります: {current.id}")
            if current.full_path in seen_paths:
                raise HierarchyError(f"Group階層に重複Full Pathがあります: {current.full_path}")
            seen_ids.add(current.id)
            seen_paths.add(current.full_path)
            nodes.append(current)

            children = self.client.list_all(f"/groups/{current.id}/subgroups")
            child_nodes = [
                self._to_node(child, root_full_path, current.depth + 1) for child in children
            ]
            for child in child_nodes:
                if child.parent_id not in (None, current.id):
                    raise HierarchyError(
                        f"Subgroupのparent_idがAPI取得元と一致しません: {child.full_path}"
                    )
            child_nodes.sort(key=lambda item: item.relative_path)
            if order == "depth_first":
                child_nodes.reverse()
            pending.extend(child_nodes)
        return nodes

    @staticmethod
    def _to_node(payload: dict[str, Any], root_full_path: str, depth: int) -> GroupNode:
        """API payloadを正規化済みGroupNodeへ変換する。"""
        full_path = str(payload["full_path"])
        if full_path == root_full_path:
            relative_path = "."
        elif full_path.startswith(f"{root_full_path}/"):
            relative_path = full_path[len(root_full_path) + 1 :]
        else:
            raise HierarchyError(
                f"Groupが指定ルート配下にありません: root={root_full_path}, group={full_path}"
            )
        return GroupNode(
            id=int(payload["id"]),
            name=str(payload.get("name", "")),
            path=str(payload.get("path", "")),
            full_path=full_path,
            parent_id=int(payload["parent_id"]) if payload.get("parent_id") is not None else None,
            relative_path=relative_path,
            depth=depth,
            description=str(payload.get("description") or ""),
            visibility=str(payload.get("visibility") or "private"),
        )
