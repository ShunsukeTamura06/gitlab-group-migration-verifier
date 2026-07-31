"""GitLab Project Export。"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

from .client import ApiResponse, GitLabClient
from .errors import ExportTimeoutError, GitLabApiError
from .group_exporter import GroupExporter
from .models import ProjectExportResult


class ProjectExporter:
    """Project Exportの完了をStatus APIで待ち、アーカイブを保存する。"""

    RATE_LIMIT_FALLBACK_SECONDS = 60.0

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
        started = self._monotonic()
        self._request_with_rate_limit_wait(
            "POST",
            f"/projects/{project_id}/export",
            expected={200, 201, 202},
            started=started,
        )
        while self._monotonic() - started < self.timeout_seconds:
            status_response = self._request_with_rate_limit_wait(
                "GET",
                f"/projects/{project_id}/export",
                expected={200},
                started=started,
            )
            status_payload = status_response.json()
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

        response = self._request_with_rate_limit_wait(
            "GET",
            f"/projects/{project_id}/export/download",
            expected={200},
            started=started,
            timeout_seconds=self.timeout_seconds,
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

    def _request_with_rate_limit_wait(
        self,
        method: str,
        path: str,
        *,
        expected: set[int],
        started: float,
        timeout_seconds: float | None = None,
    ) -> ApiResponse:
        """429をExport全体のTimeoutまで待って再試行する。

        GitLabのProject Export Downloadは既定で1ユーザーあたり毎分1回に
        制限される。Application Rate LimitではRetry-Afterが付かない場合も
        あるため、その場合は既定の制限周期である60秒待機する。
        """
        while self._monotonic() - started < self.timeout_seconds:
            response = self.client.request(
                method,
                path,
                expected={*expected, 429},
                timeout_seconds=timeout_seconds,
            )
            if response.status != 429:
                return response
            retry_after = response.headers.get("Retry-After", "")
            wait_seconds = (
                max(self.poll_interval_seconds, float(retry_after))
                if retry_after.isdigit()
                else max(
                    self.poll_interval_seconds,
                    self.RATE_LIMIT_FALLBACK_SECONDS,
                )
            )
            remaining = self.timeout_seconds - (self._monotonic() - started)
            if wait_seconds >= remaining:
                break
            self._sleep(wait_seconds)
        raise ExportTimeoutError(
            "Project ExportがGitLabのレート制限解除を待機中に"
            f"{self.timeout_seconds:g}秒のTimeoutへ達しました: {path}"
        )
