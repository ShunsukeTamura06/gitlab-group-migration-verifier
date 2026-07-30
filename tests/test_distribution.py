"""利用者向け配布物の境界を検証する。"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch

from gitlab_migrator import __version__
from gitlab_migrator.cli import _client_from_env, build_parser, run
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

        with patch.dict(
            os.environ,
            environment,
            clear=True,
        ), self.assertRaisesRegex(
            ConfigurationError,
            "SOURCE_GITLAB_TOKEN",
        ):
            _client_from_env("SOURCE")

    def test_cli_exposes_package_version(self) -> None:
        """問い合わせ時に利用者が実行Versionを確認できる。"""
        output = io.StringIO()

        with contextlib.redirect_stdout(output), self.assertRaisesRegex(
            SystemExit,
            "0",
        ):
            build_parser().parse_args(["--version"])

        self.assertIn(__version__, output.getvalue())

    def test_source_group_listing_uses_supported_ordering(self) -> None:
        """移行元Group一覧でGitLab互換のorder_byを使用する。"""
        client = Mock()
        client.list_all.return_value = [
            {"id": 2, "name": "Beta", "path": "beta", "full_path": "root/beta"},
            {"id": 1, "name": "Alpha", "path": "alpha", "full_path": "alpha"},
        ]

        with patch("gitlab_migrator.cli.source_client", return_value=client):
            result = run(build_parser().parse_args(["list-groups"]))

        client.list_all.assert_called_once_with(
            "/groups",
            params={"order_by": "path", "sort": "asc", "owned": "true"},
        )
        self.assertEqual([1, 2], [group["id"] for group in result])

    def test_destination_group_listing_uses_supported_ordering(self) -> None:
        """移行先Group一覧でもGitLab互換のorder_byを使用する。"""
        client = Mock()
        client.list_all.return_value = [
            {"id": 2, "name": "Beta", "path": "beta", "full_path": "root/beta"},
            {"id": 1, "name": "Alpha", "path": "alpha", "full_path": "alpha"},
        ]

        with patch("gitlab_migrator.cli.destination_client", return_value=client):
            result = run(
                build_parser().parse_args(["list-destination-groups"])
            )

        client.list_all.assert_called_once_with(
            "/groups",
            params={"order_by": "path", "sort": "asc"},
        )
        self.assertEqual([1, 2], [group["id"] for group in result])


if __name__ == "__main__":
    unittest.main()
