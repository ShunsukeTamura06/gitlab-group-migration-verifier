"""移行元と移行先のGroupツリーおよびデータ比較。"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any, Callable, Hashable

from .client import GitLabClient
from .hierarchy import GroupHierarchy
from .models import GroupNode, VerificationResult


class GroupVerifier:
    """内部IDではなく相対パスと論理キーでGroupを比較する。"""

    def __init__(self, source: GitLabClient, destination: GitLabClient) -> None:
        """Verifierを初期化する。"""
        self.source = source
        self.destination = destination

    def verify(self, source_group_id: int, destination_group_id: int) -> VerificationResult:
        """Group階層、Label、Milestoneを比較する。"""
        return self.compare_snapshots(
            self.capture(self.source, source_group_id),
            self.capture(self.destination, destination_group_id),
        )

    def verify_snapshot(
        self,
        source_snapshot: dict[str, Any],
        destination_group_id: int,
    ) -> VerificationResult:
        """保存済み移行元スナップショットと稼働中の移行先を比較する。"""
        return self.compare_snapshots(
            source_snapshot,
            self.capture(self.destination, destination_group_id),
        )

    @staticmethod
    def capture(client: GitLabClient, group_id: int) -> dict[str, Any]:
        """逐次起動検証用にGroup階層と比較対象データを取得する。"""
        nodes = GroupHierarchy(client).fetch(group_id)
        groups = []
        for node in nodes:
            payload = asdict(node)
            payload["labels"] = client.list_all(f"/groups/{node.id}/labels")
            payload["milestones"] = client.list_all(f"/groups/{node.id}/milestones")
            groups.append(payload)
        return {"root_group_id": group_id, "groups": groups}

    @classmethod
    def compare_snapshots(
        cls,
        source_snapshot: dict[str, Any],
        destination_snapshot: dict[str, Any],
    ) -> VerificationResult:
        """2つの正規化済みGroupスナップショットを比較する。"""
        source_groups = cls._snapshot_groups(source_snapshot)
        destination_groups = cls._snapshot_groups(destination_snapshot)
        source_nodes = [item["node"] for item in source_groups.values()]
        destination_nodes = [item["node"] for item in destination_groups.values()]
        source_by_relative = {node.relative_path: node for node in source_nodes}
        destination_by_relative = {node.relative_path: node for node in destination_nodes}
        source_paths = set(source_by_relative)
        destination_paths = set(destination_by_relative)
        common_paths = sorted(source_paths & destination_paths)
        changed_groups = cls._changed_groups(
            source_by_relative, destination_by_relative, common_paths
        )

        label_differences: list[dict[str, Any]] = []
        milestone_differences: list[dict[str, Any]] = []
        for relative_path in common_paths:
            source_node = source_by_relative[relative_path]
            destination_node = destination_by_relative[relative_path]
            label_differences.extend(
                cls._compare_resource(
                    relative_path,
                    source_groups[relative_path]["labels"],
                    destination_groups[relative_path]["labels"],
                    cls._label_key,
                )
            )
            milestone_differences.extend(
                cls._compare_resource(
                    relative_path,
                    source_groups[relative_path]["milestones"],
                    destination_groups[relative_path]["milestones"],
                    cls._milestone_key,
                )
            )

        missing = sorted(source_paths - destination_paths)
        extra = sorted(destination_paths - source_paths)
        status = "success"
        if missing or extra or changed_groups or label_differences or milestone_differences:
            status = "warning"
        return VerificationResult(
            status=status,
            source_group_count=len(source_nodes),
            destination_group_count=len(destination_nodes),
            matched_group_count=len(common_paths),
            missing_groups=missing,
            extra_groups=extra,
            changed_groups=changed_groups,
            labels_match=not label_differences,
            milestones_match=not milestone_differences,
            label_differences=label_differences,
            milestone_differences=milestone_differences,
        )

    @classmethod
    def snapshot_nodes(cls, snapshot: dict[str, Any]) -> list[GroupNode]:
        """Group Snapshotから相対パス順のGroupNodeを復元する。"""
        groups = cls._snapshot_groups(snapshot)
        return [
            item["node"]
            for _, item in sorted(
                groups.items(),
                key=lambda pair: (
                    pair[1]["node"].depth,
                    pair[1]["node"].relative_path,
                ),
            )
        ]

    @staticmethod
    def _snapshot_groups(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Snapshotを相対パスで索引し、構造を検証する。"""
        payloads = snapshot.get("groups")
        if not isinstance(payloads, list):
            raise ValueError("Group Snapshotにgroups配列がありません")
        result: dict[str, dict[str, Any]] = {}
        node_fields = set(GroupNode.__dataclass_fields__)
        for payload in payloads:
            if not isinstance(payload, dict):
                raise ValueError("Group SnapshotのGroup要素がオブジェクトではありません")
            node = GroupNode(**{key: payload[key] for key in node_fields})
            if node.relative_path in result:
                raise ValueError(f"Group Snapshotの相対パスが重複しています: {node.relative_path}")
            result[node.relative_path] = {
                "node": node,
                "labels": payload.get("labels") or [],
                "milestones": payload.get("milestones") or [],
            }
        return result

    @staticmethod
    def _changed_groups(
        source: dict[str, GroupNode],
        destination: dict[str, GroupNode],
        common_paths: list[str],
    ) -> list[dict[str, Any]]:
        """移行で意図的に変更可能なルート名・パス以外の差分を返す。"""
        changes: list[dict[str, Any]] = []
        for relative_path in common_paths:
            source_node = source[relative_path]
            destination_node = destination[relative_path]
            fields = ["description", "visibility"]
            if relative_path != ".":
                fields.extend(["name", "path"])
            field_changes = {
                field: {
                    "source": getattr(source_node, field),
                    "destination": getattr(destination_node, field),
                }
                for field in fields
                if getattr(source_node, field) != getattr(destination_node, field)
            }
            if field_changes:
                changes.append({"relative_path": relative_path, "changes": field_changes})
        return changes

    @staticmethod
    def _compare_resource(
        relative_path: str,
        source_items: list[dict[str, Any]],
        destination_items: list[dict[str, Any]],
        key: Callable[[dict[str, Any]], Hashable],
    ) -> list[dict[str, Any]]:
        """順序と内部IDに依存せずリソースを比較する。"""
        source_counter = Counter(key(item) for item in source_items)
        destination_counter = Counter(key(item) for item in destination_items)
        if source_counter == destination_counter:
            return []
        return [
            {
                "relative_path": relative_path,
                "missing": list((source_counter - destination_counter).elements()),
                "extra": list((destination_counter - source_counter).elements()),
            }
        ]

    @staticmethod
    def _label_key(item: dict[str, Any]) -> tuple[Any, ...]:
        """Group Labelの論理比較キーを返す。"""
        return (
            item.get("name"),
            item.get("description") or "",
            str(item.get("color") or "").lower(),
            str(item.get("text_color") or "").lower(),
            item.get("priority"),
        )

    @staticmethod
    def _milestone_key(item: dict[str, Any]) -> tuple[Any, ...]:
        """Group Milestoneの論理比較キーを返す。"""
        return (
            item.get("title"),
            item.get("description") or "",
            item.get("state"),
            item.get("start_date"),
            item.get("due_date"),
        )
