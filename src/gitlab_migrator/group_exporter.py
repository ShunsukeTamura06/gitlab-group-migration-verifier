"""GitLab Group Exportの開始とアーカイブ取得。"""

from __future__ import annotations

import hashlib
import os
import re
import tarfile
import time
from collections.abc import Callable
from pathlib import Path

from .client import GitLabClient
from .errors import ArchiveValidationError, ExportTimeoutError, GitLabApiError
from .models import ExportResult


class GroupExporter:
    """Group Exportを開始し、完了したアーカイブを保存する。"""

    def __init__(
        self,
        client: GitLabClient,
        *,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 600.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Exporterを初期化する。

        Args:
            client: 移行元GitLabクライアント。
            poll_interval_seconds: Download APIの呼び出し間隔。
            timeout_seconds: Export完了までの最大待機時間。
            sleep: テスト差し替え用の待機関数。
            monotonic: テスト差し替え用の単調増加時計。
        """
        if poll_interval_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("poll intervalとtimeoutは正数で指定してください")
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def export(self, group_id: int, output_dir: Path) -> ExportResult:
        """Group Exportを実行して検証済みアーカイブを保存する。

        Args:
            group_id: 移行元Group ID。
            output_dir: アーカイブ保存先ディレクトリ。

        Returns:
            ファイルサイズとSHA-256を含むExport結果。
        """
        encoded_id = self.client.encode_id(group_id)
        group = self.client.get_json(f"/groups/{encoded_id}")
        if not isinstance(group, dict):
            raise GitLabApiError("Group取得APIがオブジェクト以外を返しました")
        self.client.request("POST", f"/groups/{encoded_id}/export", expected={200, 201, 202})

        archive = self._wait_for_archive(encoded_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = self._safe_slug(str(group.get("path") or group_id))
        destination = output_dir / f"{group_id}-{slug}.tar.gz"
        partial = destination.with_suffix(destination.suffix + ".part")
        partial.write_bytes(archive)
        try:
            self._validate_archive(partial)
            os.replace(partial, destination)
            os.chmod(destination, 0o600)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return ExportResult(
            group_id=group_id,
            archive_path=destination,
            archive_size=destination.stat().st_size,
            sha256=self._sha256(destination),
        )

    def _wait_for_archive(self, encoded_id: str) -> bytes:
        """Download APIが200を返すまで待機する。"""
        started = self._monotonic()
        while self._monotonic() - started < self.timeout_seconds:
            response = self.client.request(
                "GET",
                f"/groups/{encoded_id}/export/download",
                expected={200, 404, 429},
                timeout_seconds=self.timeout_seconds,
            )
            if response.status == 200:
                if not response.body:
                    raise ArchiveValidationError("Group Exportアーカイブが空です")
                return response.body
            retry_after = response.headers.get("Retry-After", "")
            wait_seconds = (
                max(self.poll_interval_seconds, float(retry_after))
                if retry_after.isdigit()
                else self.poll_interval_seconds
            )
            self._sleep(wait_seconds)
        raise ExportTimeoutError(
            f"Group Exportが{self.timeout_seconds:g}秒以内に完了しませんでした"
        )

    @staticmethod
    def _validate_archive(path: Path) -> None:
        """gzip圧縮されたtarとして読めることと危険なパスがないことを確認する。"""
        try:
            with tarfile.open(path, mode="r:gz") as archive:
                members = archive.getmembers()
                if not members:
                    raise ArchiveValidationError("Group Exportアーカイブにファイルがありません")
                for member in members:
                    member_path = Path(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise ArchiveValidationError(
                            f"Group Exportアーカイブに危険なパスがあります: {member.name}"
                        )
        except (tarfile.TarError, OSError) as exc:
            raise ArchiveValidationError("有効なtar.gzアーカイブではありません") from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        """ファイルのSHA-256を計算する。"""
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_slug(value: str) -> str:
        """ファイル名として安全な短いslugを生成する。"""
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
        return sanitized[:80] or "group"
