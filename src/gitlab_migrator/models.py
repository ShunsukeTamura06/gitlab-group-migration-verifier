"""移行処理のデータモデル。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Group Exportの結果。"""

    group_id: int
    archive_path: Path
    archive_size: int
    sha256: str
    status: str = "finished"

    def to_dict(self) -> dict[str, Any]:
        """JSON保存可能な辞書へ変換する。"""
        result = asdict(self)
        result["archive_path"] = str(self.archive_path)
        return result


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Group Importの結果。"""

    group_id: int
    full_path: str
    response: dict[str, Any]
    resolved_by: str
    status: str = "finished"


@dataclass(frozen=True, slots=True)
class ProjectExportResult:
    """Project Exportの結果。"""

    project_id: int
    archive_path: Path
    archive_size: int
    sha256: str
    status: str = "finished"

    def to_dict(self) -> dict[str, Any]:
        """JSON保存可能な辞書へ変換する。"""
        result = asdict(self)
        result["archive_path"] = str(self.archive_path)
        return result


@dataclass(frozen=True, slots=True)
class ProjectImportResult:
    """Project Importの結果。"""

    project_id: int
    full_path: str
    response: dict[str, Any]
    resolved_by: str
    status: str = "finished"


@dataclass(frozen=True, slots=True)
class GroupNode:
    """トップレベルからの相対位置を持つGroup。"""

    id: int
    name: str
    path: str
    full_path: str
    parent_id: int | None
    relative_path: str
    depth: int
    description: str = ""
    visibility: str = "private"


@dataclass(frozen=True, slots=True)
class NamespaceMapping:
    """移行元と移行先のNamespace対応。"""

    source_group_id: int
    source_full_path: str
    destination_group_id: int
    destination_full_path: str
    source_parent_id: int | None
    destination_parent_id: int | None


@dataclass(slots=True)
class VerificationResult:
    """Group階層とGroupデータの比較結果。"""

    status: str
    source_group_count: int
    destination_group_count: int
    matched_group_count: int
    missing_groups: list[str] = field(default_factory=list)
    extra_groups: list[str] = field(default_factory=list)
    changed_groups: list[dict[str, Any]] = field(default_factory=list)
    labels_match: bool | None = None
    milestones_match: bool | None = None
    label_differences: list[dict[str, Any]] = field(default_factory=list)
    milestone_differences: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON保存可能な辞書へ変換する。"""
        return asdict(self)
