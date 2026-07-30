"""Markdownレポート生成のテスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gitlab_migrator.report import write_markdown_report


class ReportTest(unittest.TestCase):
    """Project配置を含むレポート表示を検証する。"""

    def test_reports_complete_project_placement(self) -> None:
        """全Projectが正しいNamespaceなら完全一致と表示する。"""
        manifest = {
            "tool": {"version": "1.1.0"},
            "source": {"project_count": 1},
            "verification": {
                "status": "success",
                "labels_match": True,
                "milestones_match": True,
            },
            "projects": [{"verification_status": "success"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.md"
            write_markdown_report(manifest, output)
            content = output.read_text(encoding="utf-8")
        self.assertIn("プロジェクトのNamespace配置: 完全一致", content)
        self.assertIn("Tool Version: 1.1.0", content)

    def test_reports_personal_namespace_author_mapping_limitation(self) -> None:
        """個人Projectレポートへ投稿者集約の制約を残す。"""
        manifest = {
            "tool": {"version": "1.3.0"},
            "migration_type": "personal_projects",
            "status": "success",
            "source": {"project_count": 1},
            "projects": [
                {
                    "source_path": "old-user/alpha",
                    "destination_path": "new-user/alpha",
                    "verification_status": "success",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "personal.md"
            write_markdown_report(manifest, output)
            content = output.read_text(encoding="utf-8")

        self.assertIn("GitLab個人Project移行検証レポート", content)
        self.assertIn("後から再割り当てできません", content)
        self.assertIn("old-user/alpha", content)
        self.assertIn("new-user/alpha", content)


if __name__ == "__main__":
    unittest.main()
