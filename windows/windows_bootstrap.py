"""Windows配布物を検証し、専用環境で移行ウィザードを起動する。"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import venv
from collections.abc import Sequence
from pathlib import Path

MINIMUM_PYTHON = (3, 11)


class BootstrapError(RuntimeError):
    """Windows配布物の準備に失敗したことを表す。"""


def configure_console() -> None:
    """日本語を表示できるよう標準入出力のEncodingを調整する。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def sha256(path: Path) -> str:
    """ファイルのSHA-256を計算する。

    Args:
        path: 検査対象ファイル。

    Returns:
        16進数表記のSHA-256。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_checksum(checksum_file: Path, filename: str) -> str:
    """Checksum一覧から指定ファイルの期待値を取得する。

    Args:
        checksum_file: SHA256SUMSファイル。
        filename: 検索するファイル名。

    Returns:
        小文字へ正規化したChecksum。

    Raises:
        BootstrapError: 対応するChecksumがない、または形式が不正な場合。
    """
    if not checksum_file.is_file():
        raise BootstrapError("SHA256SUMSがありません。ZIPをもう一度展開してください")
    for raw_line in checksum_file.read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        checksum, listed_name = parts
        if listed_name.lstrip("*") == filename:
            if len(checksum) != 64 or any(
                character not in "0123456789abcdefABCDEF" for character in checksum
            ):
                raise BootstrapError(f"{filename}のChecksum形式が不正です")
            return checksum.lower()
    raise BootstrapError(f"SHA256SUMSに{filename}がありません")


def find_wheel(bundle_directory: Path) -> Path:
    """配布Directory内の唯一のWheelを返す。

    Args:
        bundle_directory: 展開済み配布Directory。

    Returns:
        WheelのPath。

    Raises:
        BootstrapError: Wheelが一つでない場合。
    """
    wheels = sorted(bundle_directory.glob("gitlab_group_migrator-*.whl"))
    if len(wheels) != 1:
        raise BootstrapError(
            "移行ツール本体が見つからないか複数あります。ZIPをもう一度展開してください"
        )
    return wheels[0]


def verify_wheel(bundle_directory: Path) -> Path:
    """同梱Wheelの完全性を検査する。

    Args:
        bundle_directory: 展開済み配布Directory。

    Returns:
        検査に成功したWheelのPath。

    Raises:
        BootstrapError: Checksumが一致しない場合。
    """
    wheel = find_wheel(bundle_directory)
    expected = expected_checksum(bundle_directory / "SHA256SUMS", wheel.name)
    actual = sha256(wheel)
    if actual != expected:
        raise BootstrapError(
            "移行ツール本体のChecksumが一致しません。使用を中止し、"
            "GitHub ReleaseからZIPを再取得してください"
        )
    return wheel


def virtualenv_python(venv_directory: Path) -> Path:
    """Windows仮想環境のPython Pathを返す。

    Args:
        venv_directory: 仮想環境Directory。

    Returns:
        Python実行ファイルのPath。
    """
    return venv_directory / "Scripts" / "python.exe"


def prepare_environment(bundle_directory: Path, wheel: Path) -> Path:
    """専用仮想環境を作成してWheelをInstallする。

    Args:
        bundle_directory: 展開済み配布Directory。
        wheel: 検査済みWheel。

    Returns:
        仮想環境のPython Path。

    Raises:
        BootstrapError: 仮想環境作成またはInstallに失敗した場合。
    """
    venv_directory = bundle_directory / ".venv"
    python = virtualenv_python(venv_directory)
    if not python.is_file():
        print("初回準備: このフォルダー専用の実行環境を作成しています...")
        try:
            venv.EnvBuilder(with_pip=True, clear=True).create(venv_directory)
        except (OSError, subprocess.SubprocessError) as exc:
            raise BootstrapError(f"専用実行環境を作成できません: {exc}") from exc
    try:
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--force-reinstall",
                str(wheel),
            ],
            cwd=bundle_directory,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BootstrapError(f"移行ツールをInstallできません: {exc}") from exc
    return python


def build_parser() -> argparse.ArgumentParser:
    """Bootstrapの引数Parserを作成する。"""
    parser = argparse.ArgumentParser(description="Windows配布物の準備と起動")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="配布物のChecksum検査だけを行う",
    )
    parser.add_argument(
        "--clear-saved-tokens",
        action="store_true",
        help="Windows資格情報マネージャーの保存済みTokenを削除する",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Windows Bootstrapを実行する。

    Args:
        argv: Command Line引数。

    Returns:
        Process終了Code。
    """
    configure_console()
    args = build_parser().parse_args(argv)
    bundle_directory = Path(__file__).resolve().parent
    try:
        if sys.version_info < MINIMUM_PYTHON:
            raise BootstrapError(
                "Python 3.11以上が必要です。"
                f"現在は{sys.version_info.major}.{sys.version_info.minor}です"
            )
        print("配布物のChecksumを確認しています...")
        wheel = verify_wheel(bundle_directory)
        print("Checksum: OK")
        if args.verify_only:
            return 0
        python = prepare_environment(bundle_directory, wheel)
        wizard = bundle_directory / "migration_wizard.py"
        if not wizard.is_file():
            raise BootstrapError(
                "migration_wizard.pyがありません。ZIPをもう一度展開してください"
            )
        wizard_arguments = (
            ["--clear-saved-tokens"] if args.clear_saved_tokens else []
        )
        return subprocess.run(
            [str(python), str(wizard), *wizard_arguments],
            cwd=bundle_directory,
            check=False,
        ).returncode
    except BootstrapError as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
