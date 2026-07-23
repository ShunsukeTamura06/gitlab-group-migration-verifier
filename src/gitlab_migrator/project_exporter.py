"""最小検証用Project Export。"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from .client import GitLabClient
from .errors import ExportTimeoutError, GitLabApiError
from .group_exporter import GroupExporter
from .models import ProjectExportResult


class ProjectExporter:
    """Project Exportの完了をStatus APIで待ち、アーカイブを保存する。"""

    def __init__(
        self,
        client: GitLabClient,
        *,
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Project Exporterを初期化する。"""
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def export(self, project_id: int, output_dir: Path) -> ProjectExportResult:
        """ProjectをExportし、検証済みアーカイブを保存する。"""
        project = self.client.get_json(f"/projects/{project_id}")
        if not isinstance(project, dict):
            raise GitLabApiError("Project取得APIがオブジェクト以外を返しました")
        self.client.request("POST", f"/projects/{project_id}/export", expected={200, 201, 202})
        started = self._monotonic()
        while self._monotonic() - started < self.timeout_seconds:
            status_payload = self.client.get_json(f"/projects/{project_id}/export")
            if not isinstance(status_payload, dict):
                raise GitLabApiError("Project Export Status APIの応答が不正です")
            status = str(status_payload.get("export_status") or "")
            if status == "finished":
                break
            if status in {"failed", "canceled"}:
                raise GitLabApiError(f"Project Exportが失敗しました: status={status}")
            self._sleep(self.poll_interval_seconds)
        else:
            raise ExportTimeoutError(
                f"Project Exportが{self.timeout_seconds:g}秒以内に完了しませんでした"
            )

        response = self.client.request(
            "GET", f"/projects/{project_id}/export/download", expected={200}
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        path = str(project.get("path") or project_id)
        destination = output_dir / f"{project_id}-{GroupExporter._safe_slug(path)}.tar.gz"
        partial = destination.with_suffix(destination.suffix + ".part")
        partial.write_bytes(response.body)
        try:
            GroupExporter._validate_archive(partial)
            partial.replace(destination)
            os.chmod(destination, 0o600)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return ProjectExportResult(
            project_id=project_id,
            archive_path=destination,
            archive_size=destination.stat().st_size,
            sha256=GroupExporter._sha256(destination),
        )
