"""移行Manifestの安全な保存。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SENSITIVE_KEY_PARTS = ("token", "password", "secret", "authorization", "private-token")


def redact_secrets(value: Any) -> Any:
    """辞書や配列に含まれる秘密情報らしい値を再帰的にマスクする。

    Args:
        value: APIレスポンスなどのJSON互換値。

    Returns:
        秘密情報を`[MASKED]`へ置換した値。
    """
    if isinstance(value, dict):
        return {
            str(key): (
                "[MASKED]"
                if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
                else redact_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


class ManifestStore:
    """Manifestを一時ファイル経由で原子的に保存する。"""

    def __init__(self, path: Path) -> None:
        """保存先を指定して初期化する。"""
        self.path = path

    def save(self, manifest: dict[str, Any]) -> None:
        """秘密情報をマスクしてManifestを保存する。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(redact_secrets(manifest), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def load(self) -> dict[str, Any]:
        """保存済みManifestを読み込む。"""
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("ManifestのルートはJSONオブジェクトである必要があります")
        return payload
