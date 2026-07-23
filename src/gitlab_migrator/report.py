"""Group移行ManifestからMarkdownレポートを生成する。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def write_markdown_report(manifest: dict[str, Any], output: Path) -> None:
    """Group移行結果を判定根拠付きMarkdownとして保存する。"""
    verification = manifest.get("verification") or {}
    projects = manifest.get("projects") or []
    expected_project_count = int(
        (manifest.get("source") or {}).get("project_count") or 0
    )
    project_failures = [
        item for item in projects if item.get("verification_status") != "success"
    ]
    if expected_project_count == 0:
        project_result = "対象なし"
    elif len(projects) == expected_project_count and not project_failures:
        project_result = "完全一致"
    elif projects:
        project_result = "差異あり"
    else:
        project_result = "未検証"
    status = verification.get("status", "unknown")
    direct_result = "成功" if status == "success" else "部分成功" if status == "warning" else "未判定"
    missing = verification.get("missing_groups") or []
    extra = verification.get("extra_groups") or []
    changes = verification.get("changed_groups") or []
    lines = [
        "# GitLabグループ移行検証レポート",
        "",
        f"- グループ直接Export / Import: {direct_result}",
        f"- サブグループ階層: {'完全一致' if not missing and not extra else '差異あり'}",
        f"- グループラベル: {'完全一致' if verification.get('labels_match') else '差異あり'}",
        f"- グループマイルストーン: {'完全一致' if verification.get('milestones_match') else '差異あり'}",
        f"- プロジェクトのNamespace配置: {project_result}",
        "- 本番採用判断: 自動判定対象外を手動確認後に移行責任者が判定",
        "",
        "## 階層集計",
        "",
        "| 移行元 | 移行先 | 一致 | 欠落 | 余分 |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {verification.get('source_group_count', 0)} "
            f"| {verification.get('destination_group_count', 0)} "
            f"| {verification.get('matched_group_count', 0)} "
            f"| {len(missing)} | {len(extra)} |"
        ),
        "",
        "## 差分",
        "",
        f"- Missing groups: {', '.join(missing) if missing else 'なし'}",
        f"- Extra groups: {', '.join(extra) if extra else 'なし'}",
        f"- Changed groups: {len(changes)}件",
        f"- Project placement failures: {len(project_failures)}件",
        "",
        "## 根拠ファイル",
        "",
        f"- Export archive: `{(manifest.get('export') or {}).get('archive_path', '不明')}`",
        f"- SHA-256: `{(manifest.get('export') or {}).get('sha256', '不明')}`",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
