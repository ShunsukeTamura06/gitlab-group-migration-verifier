"""利用者向け配布物の境界を検証する。"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import unittest
from unittest.mock import patch

from gitlab_migrator.cli import _client_from_env, build_parser
from gitlab_migrator.errors import ConfigurationError
from gitlab_migrator import __version__


class DistributionBoundaryTest(unittest.TestCase):
    """検証専用機能が本番CLIへ混入しないことを保証する。"""

    def test_validation_only_commands_are_not_exposed(self) -> None:
        """検証環境を変更するCommandを公開しない。"""
        parser = build_parser()
        subparser_action = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        forbidden_commands = {
            "bootstrap-groups",
            "bootstrap-tree",
            "bootstrap-project",
            "smoke-group",
        }

        self.assertTrue(forbidden_commands.isdisjoint(subparser_action.choices))

    def test_root_password_does_not_replace_personal_access_token(self) -> None:
        """root Passwordが設定されてもPAT未設定なら接続設定を拒否する。"""
        environment = {
            "SOURCE_GITLAB_URL": "https://gitlab-old.internal.example",
            "SOURCE_GITLAB_ROOT_PASSWORD": "local-only-password",
        }

        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ConfigurationError,
                "SOURCE_GITLAB_TOKEN",
            ):
                _client_from_env("SOURCE")

    def test_cli_exposes_package_version(self) -> None:
        """問い合わせ時に利用者が実行Versionを確認できる。"""
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(SystemExit, "0"):
                build_parser().parse_args(["--version"])

        self.assertIn(__version__, output.getvalue())


if __name__ == "__main__":
    unittest.main()
