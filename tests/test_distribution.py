"""利用者向け配布物の境界を検証する。"""

from __future__ import annotations

import argparse
import os
import unittest
from unittest.mock import patch

from gitlab_migrator.cli import _client_from_env, build_parser
from gitlab_migrator.errors import ConfigurationError


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


if __name__ == "__main__":
    unittest.main()
