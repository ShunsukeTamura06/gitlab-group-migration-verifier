"""GitLab接続設定のテスト。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gitlab_migrator.config import GitLabConfig
from gitlab_migrator.errors import ConfigurationError


class GitLabConfigTest(unittest.TestCase):
    """環境変数の検証と社内CA設定を確認する。"""

    def test_reads_existing_ca_bundle(self) -> None:
        """接続先別のCA Bundleを読み込む。"""
        with tempfile.TemporaryDirectory() as directory:
            ca_bundle = Path(directory) / "ca.pem"
            ca_bundle.write_text("test certificate", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SOURCE_GITLAB_URL": "https://gitlab.internal.example",
                    "SOURCE_GITLAB_TOKEN": "token",
                    "SOURCE_GITLAB_CA_BUNDLE": str(ca_bundle),
                },
                clear=True,
            ):
                config = GitLabConfig.from_env("SOURCE")
        self.assertEqual(ca_bundle, config.ca_bundle)

    def test_rejects_relative_or_unsupported_url(self) -> None:
        """API URLはHTTP(S)の絶対URLだけを許可する。"""
        with patch.dict(
            os.environ,
            {
                "SOURCE_GITLAB_URL": "gitlab.internal.example",
                "SOURCE_GITLAB_TOKEN": "token",
            },
            clear=True,
        ):
            with self.assertRaises(ConfigurationError):
                GitLabConfig.from_env("SOURCE")


if __name__ == "__main__":
    unittest.main()
