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


if __name__ == "__main__":
    unittest.main()
