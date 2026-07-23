"""移行元と移行先のGroup Namespace対応管理。"""

from __future__ import annotations

from .errors import HierarchyError
from .models import GroupNode, NamespaceMapping


class NamespaceMapper:
    """相対パスを論理キーにNamespaceを対応付ける。"""

    def __init__(self, mappings: list[NamespaceMapping]) -> None:
        """Namespaceマッピングを初期化する。"""
        self.mappings = mappings
        self._by_source = {item.source_full_path: item for item in mappings}
        if len(self._by_source) != len(mappings):
            raise HierarchyError("移行元Namespaceマッピングが重複しています")

    @classmethod
    def from_trees(
        cls,
        source_nodes: list[GroupNode],
        destination_nodes: list[GroupNode],
    ) -> "NamespaceMapper":
        """相対パスが一致する2つのGroupツリーからマッピングを作る。"""
        source_by_relative = cls._unique_by_relative(source_nodes, "移行元")
        destination_by_relative = cls._unique_by_relative(destination_nodes, "移行先")
        missing = sorted(set(source_by_relative) - set(destination_by_relative))
        if missing:
            raise HierarchyError(f"移行先に対応Groupがありません: {', '.join(missing)}")
        mappings = []
        for relative_path, source in source_by_relative.items():
            destination = destination_by_relative[relative_path]
            mappings.append(
                NamespaceMapping(
                    source_group_id=source.id,
                    source_full_path=source.full_path,
                    destination_group_id=destination.id,
                    destination_full_path=destination.full_path,
                    source_parent_id=source.parent_id,
                    destination_parent_id=destination.parent_id,
                )
            )
        return cls(mappings)

    def destination_namespace(self, source_namespace: str) -> str:
        """移行元Group Full Pathに対応する移行先Full Pathを返す。"""
        try:
            return self._by_source[source_namespace].destination_full_path
        except KeyError as exc:
            raise HierarchyError(f"Namespaceマッピングが存在しません: {source_namespace}") from exc

    def destination_project_path(self, source_project_full_path: str) -> str:
        """Project Full PathのNamespace部分だけを移行先へ置換する。"""
        namespace, separator, project_path = source_project_full_path.rpartition("/")
        if not separator or not namespace or not project_path:
            raise HierarchyError(f"不正なProject Full Pathです: {source_project_full_path}")
        return f"{self.destination_namespace(namespace)}/{project_path}"

    @staticmethod
    def _unique_by_relative(nodes: list[GroupNode], label: str) -> dict[str, GroupNode]:
        """相対パスをキーにし、重複があれば失敗する。"""
        result: dict[str, GroupNode] = {}
        for node in nodes:
            if node.relative_path in result:
                raise HierarchyError(
                    f"{label}Groupツリーに相対パスの重複があります: {node.relative_path}"
                )
            result[node.relative_path] = node
        return result
