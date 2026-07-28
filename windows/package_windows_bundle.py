"""Windows向け自己完結配布ZIPを作成する。"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REQUIRED_FILES = (
    "Start-GitLabMigration.cmd",
    "windows_bootstrap.py",
    "migration_wizard.py",
    "README-WINDOWS.txt",
)


def wheel_version(wheel: Path) -> str:
    """Wheel名からVersionを取得する。

    Args:
        wheel: 配布対象Wheel。

    Returns:
        WheelのVersion。

    Raises:
        ValueError: 想定したWheel名でない場合。
    """
    match = re.fullmatch(
        r"gitlab_group_migrator-([A-Za-z0-9_.!+-]+)-py3-none-any\.whl",
        wheel.name,
    )
    if match is None:
        raise ValueError(f"想定外のWheel名です: {wheel.name}")
    return match.group(1)


def sha256(path: Path) -> str:
    """ファイルのSHA-256を計算する。

    Args:
        path: 計算対象。

    Returns:
        16進数表記のSHA-256。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_bundle(wheel: Path, output_directory: Path) -> Path:
    """Windows向け配布ZIPを作る。

    Args:
        wheel: 同梱するWheel。
        output_directory: ZIP出力先。

    Returns:
        作成したZIPのPath。

    Raises:
        FileNotFoundError: 必須ファイルがない場合。
    """
    wheel = wheel.resolve()
    if not wheel.is_file():
        raise FileNotFoundError(wheel)
    version = wheel_version(wheel)
    source_directory = Path(__file__).resolve().parent
    for filename in REQUIRED_FILES:
        source = source_directory / filename
        if not source.is_file():
            raise FileNotFoundError(source)
    output_directory.mkdir(parents=True, exist_ok=True)
    bundle_name = f"gitlab-group-migrator-windows-v{version}"
    output_path = output_directory.resolve() / f"{bundle_name}.zip"
    with tempfile.TemporaryDirectory() as temporary:
        bundle_directory = Path(temporary) / bundle_name
        bundle_directory.mkdir()
        for filename in REQUIRED_FILES:
            shutil.copy2(source_directory / filename, bundle_directory / filename)
        shutil.copy2(wheel, bundle_directory / wheel.name)
        (bundle_directory / "SHA256SUMS").write_text(
            f"{sha256(wheel)}  {wheel.name}\n",
            encoding="utf-8",
        )
        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(bundle_directory.iterdir()):
                archive.write(path, arcname=f"{bundle_name}/{path.name}")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    """配布Scriptの引数Parserを生成する。"""
    parser = argparse.ArgumentParser(description="Windows向け配布ZIPを作成")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Windows向け配布ZIP作成のEntry Point。

    Args:
        argv: Command Line引数。

    Returns:
        Process終了Code。
    """
    args = build_parser().parse_args(argv)
    output = create_bundle(args.wheel, args.output_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
