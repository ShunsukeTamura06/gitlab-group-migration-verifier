"""テスト用ヘルパー。"""

from __future__ import annotations

import io
import tarfile


def tar_gz_bytes(name: str = "tree/project.json", content: bytes = b"{}") -> bytes:
    """メモリ上に最小tar.gzアーカイブを作成する。"""
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


class Clock:
    """sleepでのみ進むテスト用時計。"""

    def __init__(self) -> None:
        """時刻0で初期化する。"""
        self.value = 0.0

    def monotonic(self) -> float:
        """現在時刻を返す。"""
        return self.value

    def sleep(self, seconds: float) -> None:
        """指定秒数だけ時計を進める。"""
        self.value += seconds
