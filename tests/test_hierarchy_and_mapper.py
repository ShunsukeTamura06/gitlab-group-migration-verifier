"""Group階層とNamespaceマッピングのテスト。"""

from __future__ import annotations

import unittest

from gitlab_migrator.errors import HierarchyError
from gitlab_migrator.hierarchy import GroupHierarchy
from gitlab_migrator.models import GroupNode
from gitlab_migrator.namespace_mapper import NamespaceMapper


class HierarchyClient:
    """階層API向けFakeクライアント。"""

    groups = {
        1: {
            "id": 1,
            "name": "root",
            "path": "root",
            "full_path": "root",
            "parent_id": None,
            "visibility": "private",
        }
    }
    children = {
        1: [
            {
                "id": 2,
                "name": "platform",
                "path": "platform",
                "full_path": "root/platform",
                "parent_id": 1,
            }
        ],
        2: [
            {
                "id": 3,
                "name": "backend",
                "path": "backend",
                "full_path": "root/platform/backend",
                "parent_id": 2,
            }
        ],
        3: [],
    }

    @staticmethod
    def encode_id(value: object) -> str:
        """IDを文字列化する。"""
        return str(value)

    def get_json(self, path: str) -> dict[str, object]:
        """ルートGroupを返す。"""
        return self.groups[int(path.rsplit("/", 1)[1])]

    def list_all(self, path: str, **_kwargs: object) -> list[dict[str, object]]:
        """直下Subgroupを返す。"""
        group_id = int(path.split("/")[2])
        return self.children[group_id]


def node(
    group_id: int,
    full_path: str,
    relative_path: str,
    parent_id: int | None,
) -> GroupNode:
    """NamespaceMapper用GroupNodeを作成する。"""
    path = full_path.rsplit("/", 1)[-1]
    return GroupNode(
        id=group_id,
        name=path,
        path=path,
        full_path=full_path,
        parent_id=parent_id,
        relative_path=relative_path,
        depth=0 if relative_path == "." else relative_path.count("/") + 1,
    )


class HierarchyAndMapperTest(unittest.TestCase):
    """相対パス正規化とProject配置を検証する。"""

    def test_fetches_nested_tree_with_relative_paths(self) -> None:
        """2階層以上のSubgroupを相対パスへ正規化する。"""
        nodes = GroupHierarchy(HierarchyClient()).fetch(1)  # type: ignore[arg-type]
        self.assertEqual(
            [".", "platform", "platform/backend"],
            [item.relative_path for item in nodes],
        )
        self.assertEqual([0, 1, 2], [item.depth for item in nodes])

    def test_maps_project_to_matching_destination_namespace(self) -> None:
        """Project名を変えずNamespaceのルートだけを置換する。"""
        source = [
            node(1, "source", ".", None),
            node(2, "source/platform", "platform", 1),
        ]
        destination = [
            node(10, "destination", ".", None),
            node(20, "destination/platform", "platform", 10),
        ]
        mapper = NamespaceMapper.from_trees(source, destination)
        self.assertEqual(
            "destination/platform/api-service",
            mapper.destination_project_path("source/platform/api-service"),
        )

    def test_fails_if_destination_group_is_missing(self) -> None:
        """対応Subgroupが欠落したマッピングは作成しない。"""
        source = [node(1, "source", ".", None), node(2, "source/data", "data", 1)]
        destination = [node(10, "destination", ".", None)]
        with self.assertRaises(HierarchyError):
            NamespaceMapper.from_trees(source, destination)


if __name__ == "__main__":
    unittest.main()
