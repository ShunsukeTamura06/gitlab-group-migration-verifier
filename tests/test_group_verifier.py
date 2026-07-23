"""Group比較処理のテスト。"""

from __future__ import annotations

import unittest

from gitlab_migrator.group_verifier import GroupVerifier


class VerifyClient:
    """Verifier向けGroup、Label、Milestone API。"""

    def __init__(self, root_id: int, root_path: str, label_color: str = "#D9534F") -> None:
        """ルート情報とLabel色を保持する。"""
        self.root_id = root_id
        self.root_path = root_path
        self.label_color = label_color

    @staticmethod
    def encode_id(value: object) -> str:
        """IDを文字列化する。"""
        return str(value)

    def get_json(self, _path: str) -> dict[str, object]:
        """ルートGroupを返す。"""
        return {
            "id": self.root_id,
            "name": self.root_path,
            "path": self.root_path,
            "full_path": self.root_path,
            "parent_id": None,
            "description": "same",
            "visibility": "private",
        }

    def list_all(self, path: str, **_kwargs: object) -> list[dict[str, object]]:
        """要求されたGroupデータを返す。"""
        if path.endswith("/subgroups"):
            return []
        if path.endswith("/labels"):
            return [
                {
                    "name": "重要",
                    "description": "same",
                    "color": self.label_color,
                    "text_color": "#FFFFFF",
                    "priority": None,
                }
            ]
        if path.endswith("/milestones"):
            return [
                {
                    "title": "M1",
                    "description": "same",
                    "state": "active",
                    "start_date": "2026-01-01",
                    "due_date": "2026-02-01",
                }
            ]
        raise AssertionError(path)


class GroupVerifierTest(unittest.TestCase):
    """内部IDと意図的なルート名変更を比較対象外にすることを検証する。"""

    def test_accepts_root_rename_and_case_insensitive_colors(self) -> None:
        """ルート名変更と色表記の大文字小文字だけでは差分にしない。"""
        result = GroupVerifier(
            VerifyClient(1, "source", "#D9534F"),  # type: ignore[arg-type]
            VerifyClient(20, "destination", "#d9534f"),  # type: ignore[arg-type]
        ).verify(1, 20)
        self.assertEqual("success", result.status)
        self.assertTrue(result.labels_match)
        self.assertTrue(result.milestones_match)

    def test_reports_label_difference(self) -> None:
        """Labelの論理属性差分を警告として返す。"""
        result = GroupVerifier(
            VerifyClient(1, "source", "#D9534F"),  # type: ignore[arg-type]
            VerifyClient(20, "destination", "#000000"),  # type: ignore[arg-type]
        ).verify(1, 20)
        self.assertEqual("warning", result.status)
        self.assertFalse(result.labels_match)
        self.assertEqual(1, len(result.label_differences))


if __name__ == "__main__":
    unittest.main()
