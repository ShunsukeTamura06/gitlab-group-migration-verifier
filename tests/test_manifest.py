"""Manifest保存のテスト。"""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from gitlab_migrator.manifest import ManifestStore, redact_secrets


class ManifestTest(unittest.TestCase):
    """秘密情報マスクと原子的保存を検証する。"""

    def test_redacts_nested_secrets(self) -> None:
        """APIレスポンス内のToken類を再帰的にマスクする。"""
        result = redact_secrets(
            {
                "private_token": "secret-value",
                "nested": [{"password": "pw", "name": "safe"}],
            }
        )
        self.assertEqual("[MASKED]", result["private_token"])
        self.assertEqual("[MASKED]", result["nested"][0]["password"])
        self.assertEqual("safe", result["nested"][0]["name"])

    def test_round_trip(self) -> None:
        """UTF-8のManifestを保存して読み戻せる。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            store = ManifestStore(path)
            store.save({"name": "日本語", "token": "hidden"})
            self.assertEqual(
                {"name": "日本語", "token": "[MASKED]"},
                store.load(),
            )
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))


if __name__ == "__main__":
    unittest.main()
