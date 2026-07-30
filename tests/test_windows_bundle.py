"""Windows向け簡単配布物の振る舞いを検証する。"""

from __future__ import annotations

import getpass
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from windows import (
    configure_distribution,
    migration_wizard,
    package_windows_bundle,
    windows_bootstrap,
)


class WindowsBundleTest(unittest.TestCase):
    """Windows向け配布ZIPとBootstrapを検証する。"""

    def test_bundle_contains_only_required_user_files(self) -> None:
        """生成ZIPに起動・検査・案内・Wheelを含める。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "gitlab_group_migrator-1.2.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel-content")

            bundle = package_windows_bundle.create_bundle(wheel, root / "dist")

            with ZipFile(bundle) as archive:
                names = archive.namelist()
                checksum_name = next(name for name in names if name.endswith("/SHA256SUMS"))
                checksum = archive.read(checksum_name).decode("utf-8")
                example_name = next(
                    name
                    for name in names
                    if name.endswith("/migration-settings.example.json")
                )
                example = json.loads(archive.read(example_name))
            self.assertTrue(any(name.endswith("/Start-GitLabMigration.cmd") for name in names))
            self.assertTrue(any(name.endswith("/Configure-Distribution.cmd") for name in names))
            self.assertTrue(any(name.endswith("/migration_wizard.py") for name in names))
            self.assertTrue(any(name.endswith("/configure_distribution.py") for name in names))
            self.assertTrue(any(name.endswith("/MIGRATION-SCOPE.md") for name in names))
            self.assertTrue(
                any(name.endswith("/migration-settings.example.json") for name in names)
            )
            self.assertTrue(any(name.endswith(f"/{wheel.name}") for name in names))
            self.assertIn(windows_bootstrap.sha256(wheel), checksum)
            self.assertFalse(any("/tests/" in name for name in names))
            self.assertFalse(any(name.endswith("/migration-settings.json") for name in names))
            self.assertTrue(
                str(example["source_gitlab_url"]).endswith(".invalid")
            )
            self.assertTrue(
                str(example["destination_gitlab_url"]).endswith(".invalid")
            )

    def test_bundle_batch_launchers_are_ascii_crlf(self) -> None:
        """CMDを文字化けしないASCII・CRLF形式で梱包する。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "gitlab_group_migrator-1.2.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel-content")

            bundle = package_windows_bundle.create_bundle(wheel, root / "dist")

            with ZipFile(bundle) as archive:
                command_files = {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if name.endswith(".cmd")
                }
            self.assertEqual(2, len(command_files))
            for name, content in command_files.items():
                with self.subTest(name=name):
                    self.assertTrue(content.isascii())
                    self.assertFalse(content.startswith(b"\xef\xbb\xbf"))
                    self.assertIn(b"\r\n", content)
                    self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
                    self.assertIn(b"GITLAB_MIGRATOR_NO_PAUSE", content)

    def test_bootstrap_rejects_tampered_wheel(self) -> None:
        """同梱Wheelが変更されていたら起動前に拒否する。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wheel = root / "gitlab_group_migrator-1.2.0-py3-none-any.whl"
            wheel.write_bytes(b"original")
            (root / "SHA256SUMS").write_text(
                f"{windows_bootstrap.sha256(wheel)}  {wheel.name}\n",
                encoding="utf-8",
            )
            self.assertEqual(wheel, windows_bootstrap.verify_wheel(root))

            wheel.write_bytes(b"tampered")

            with self.assertRaisesRegex(windows_bootstrap.BootstrapError, "一致しません"):
                windows_bootstrap.verify_wheel(root)

    def test_internal_bundle_contains_urls_only_in_runtime_settings(self) -> None:
        """実URL設定を公開用ToolやTokenと混在させず社内ZIPへ入れる。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for filename in configure_distribution.INTERNAL_RUNTIME_FILES:
                (root / filename).write_text(f"dummy {filename}\n", encoding="utf-8")
            wheel = root / "gitlab_group_migrator-1.2.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel-content")
            (root / "SHA256SUMS").write_text(
                f"{windows_bootstrap.sha256(wheel)}  {wheel.name}\n",
                encoding="utf-8",
            )
            settings = configure_distribution.build_settings(
                "https://source.example.invalid",
                "https://destination.example.invalid",
                50,
            )

            bundle, checksum = configure_distribution.create_internal_bundle(
                root,
                root / "internal-distribution",
                settings,
            )

            with ZipFile(bundle) as archive:
                names = archive.namelist()
                settings_name = next(
                    name for name in names if name.endswith("/migration-settings.json")
                )
                stored_settings = json.loads(archive.read(settings_name))
            self.assertEqual(
                "https://source.example.invalid",
                stored_settings["source_gitlab_url"],
            )
            self.assertNotIn("token", json.dumps(stored_settings).lower())
            self.assertFalse(
                any(name.endswith("/Configure-Distribution.cmd") for name in names)
            )
            self.assertFalse(
                any(name.endswith("/configure_distribution.py") for name in names)
            )
            self.assertIn(windows_bootstrap.sha256(bundle), checksum.read_text())

    def test_internal_bundle_rejects_token_setting(self) -> None:
        """社内ZIP生成時にもToken項目を拒否する。"""
        with tempfile.TemporaryDirectory() as temporary:
            settings = {
                "source_gitlab_url": "https://source.example.invalid",
                "destination_gitlab_url": "https://destination.example.invalid",
                "required_free_gib": 50,
                "prompt_for_ca_bundle": False,
                "source_gitlab_token": "must-not-be-stored",
            }

            with self.assertRaisesRegex(
                configure_distribution.DistributionConfigurationError,
                "許可されていない",
            ):
                configure_distribution.create_internal_bundle(
                    Path(temporary),
                    Path(temporary) / "output",
                    settings,
                )


class MigrationWizardTest(unittest.TestCase):
    """Windows向け対話ウィザードを検証する。"""

    def test_parse_and_choose_group_by_number(self) -> None:
        """利用者がGroup IDを知らなくても番号で選べる。"""
        groups = migration_wizard.parse_groups(
            json.dumps(
                [
                    {"id": 10, "name": "Alpha", "full_path": "company/alpha"},
                    {"id": 20, "name": "Beta", "full_path": "company/beta"},
                ]
            )
        )

        selected = migration_wizard.choose_group(groups, input_function=lambda _: "2")

        self.assertEqual(20, selected["id"])

    def test_token_is_collected_without_plain_input(self) -> None:
        """Token入力には画面非表示のgetpassを利用する。"""
        answers = iter(
            [
                "https://old.example",
                "https://new.example",
                "",
                "",
            ]
        )
        with patch.object(
            getpass,
            "getpass",
            side_effect=["source-secret", "destination-secret"],
        ) as hidden_input:
            environment = migration_wizard.collect_environment(
                input_function=lambda _: next(answers)
            )

        self.assertEqual("source-secret", environment["SOURCE_GITLAB_TOKEN"])
        self.assertEqual("destination-secret", environment["DESTINATION_GITLAB_TOKEN"])
        self.assertEqual(2, hidden_input.call_count)

    def test_preconfigured_urls_skip_url_and_ca_prompts(self) -> None:
        """社内配布設定があれば利用者へURLとCAを質問しない。"""
        settings = {
            "source_gitlab_url": "https://source.example.invalid",
            "destination_gitlab_url": "https://destination.example.invalid",
            "required_free_gib": 50,
            "prompt_for_ca_bundle": False,
        }

        def unexpected_input(_: str) -> str:
            """通常入力が呼ばれたらTestを失敗させる。"""
            self.fail("URLまたはCAの入力を要求しました")

        with patch.object(
            getpass,
            "getpass",
            side_effect=["source-secret", "destination-secret"],
        ):
            environment = migration_wizard.collect_environment(
                settings=settings,
                input_function=unexpected_input,
            )

        self.assertEqual(
            "https://source.example.invalid",
            environment["SOURCE_GITLAB_URL"],
        )
        self.assertEqual(
            "https://destination.example.invalid",
            environment["DESTINATION_GITLAB_URL"],
        )
        self.assertNotIn("SOURCE_GITLAB_CA_BUNDLE", environment)
        self.assertNotIn("DESTINATION_GITLAB_CA_BUNDLE", environment)

    def test_distribution_settings_reject_secret_fields(self) -> None:
        """配布設定へToken等の許可外項目を保存させない。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / migration_wizard.SETTINGS_FILENAME).write_text(
                json.dumps(
                    {
                        "source_gitlab_url": "https://source.example.invalid",
                        "destination_gitlab_url": "https://destination.example.invalid",
                        "required_free_gib": 50,
                        "prompt_for_ca_bundle": False,
                        "source_gitlab_token": "must-not-be-stored",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(migration_wizard.WizardError, "許可されていない"):
                migration_wizard.load_distribution_settings(root)

    def test_distribution_settings_are_loaded_without_logging_urls(self) -> None:
        """社内配布設定を検証し、読み込み時にURLを表示しない。"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_url = "https://source.example.invalid"
            (root / migration_wizard.SETTINGS_FILENAME).write_text(
                json.dumps(
                    {
                        "source_gitlab_url": source_url,
                        "destination_gitlab_url": "https://destination.example.invalid",
                        "required_free_gib": 50,
                        "prompt_for_ca_bundle": False,
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                settings = migration_wizard.load_distribution_settings(root)

        self.assertEqual(source_url, settings["source_gitlab_url"])
        self.assertNotIn(source_url, output.getvalue())

    def test_destination_parent_is_selected_without_group_id_input(self) -> None:
        """移行先親Groupも一覧の番号から選択できる。"""
        destination_groups = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                [{"id": 99, "name": "Platform", "full_path": "company/platform"}]
            ),
            stderr="",
        )
        answers = iter(["2", "1"])
        with patch.object(
            migration_wizard,
            "run_cli",
            return_value=destination_groups,
        ) as run_cli:
            parent_id = migration_wizard.choose_destination_parent(
                environment={},
                bundle_directory=Path("."),
                input_function=lambda _: next(answers),
            )

        self.assertEqual("99", parent_id)
        self.assertEqual(
            "list-destination-groups",
            run_cli.call_args.args[0][0],
        )

    def test_preflight_only_never_starts_migration(self) -> None:
        """事前診断だけを選んだ場合はGitLab変更Commandを実行しない。"""
        answers = iter(
            [
                "https://old.example",
                "https://new.example",
                "",
                "",
                "1",
                "3",
                "",
                "",
                "",
                "",
            ]
        )
        group_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                [{"id": 10, "name": "Alpha", "full_path": "company/alpha"}]
            ),
            stderr="",
        )
        preflight_result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "passed",
                    "source_version": "17.0.0",
                    "destination_version": "17.0.0",
                    "checks": [],
                    "warnings": [],
                }
            ),
            stderr="",
        )
        with tempfile.TemporaryDirectory() as temporary:
            fake_file = str(Path(temporary) / "migration_wizard.py")
            with (
                patch.object(
                    getpass,
                    "getpass",
                    side_effect=["source-secret", "destination-secret"],
                ),
                patch.object(
                    migration_wizard,
                    "run_cli",
                    side_effect=[group_result, preflight_result],
                ) as run_cli,
                patch.object(migration_wizard, "__file__", fake_file),
            ):
                exit_code = migration_wizard.execute_wizard(
                    input_function=lambda _: next(answers)
                )

        self.assertEqual(0, exit_code)
        self.assertEqual(2, run_cli.call_count)
        called_arguments = [call.args[0] for call in run_cli.call_args_list]
        self.assertEqual("list-groups", called_arguments[0][0])
        self.assertEqual("preflight", called_arguments[1][0])

    def test_non_https_remote_url_is_rejected(self) -> None:
        """社内GitLab接続でTLS検証を省略させない。"""
        with self.assertRaisesRegex(migration_wizard.WizardError, "https"):
            migration_wizard.validate_url("http://gitlab.internal.example")

    def test_url_with_credentials_or_api_path_is_rejected(self) -> None:
        """URLへPasswordやAPI Pathを埋め込ませない。"""
        invalid_urls = (
            "https://user:password@gitlab.example.invalid",
            "https://gitlab.example.invalid/api/v4",
        )

        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(migration_wizard.WizardError):
                migration_wizard.validate_url(url)

    def test_long_running_migration_shows_heartbeat(self) -> None:
        """長時間処理中に利用者へ継続中であることを知らせる。"""

        class FakeProcess:
            """一度Timeoutしてから成功する子Process。"""

            def __init__(self) -> None:
                """呼び出し回数を初期化する。"""
                self.wait_count = 0

            def wait(self, timeout: float) -> int:
                """最初の待機だけTimeoutさせる。

                Args:
                    timeout: 待機上限秒。

                Returns:
                    2回目以降は成功Code。
                """
                self.wait_count += 1
                if self.wait_count == 1:
                    raise subprocess.TimeoutExpired("gitlab-migrator", timeout)
                return 0

        output = io.StringIO()
        with (
            patch.object(subprocess, "Popen", return_value=FakeProcess()),
            redirect_stdout(output),
        ):
            exit_code = migration_wizard.run_cli_with_progress(
                ["migrate-tree"],
                environment={},
                bundle_directory=Path("."),
                heartbeat_seconds=0.01,
            )

        self.assertEqual(0, exit_code)
        self.assertIn("処理を継続しています", output.getvalue())


if __name__ == "__main__":
    unittest.main()
