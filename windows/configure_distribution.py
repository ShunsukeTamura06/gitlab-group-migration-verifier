"""実URLをGit管理せず、社内専用Windows配布ZIPを生成する。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zipfile import ZIP_DEFLATED, ZipFile

try:
    from . import windows_bootstrap
except ImportError:
    import windows_bootstrap


InputFunction = Callable[[str], str]
INTERNAL_RUNTIME_FILES = (
    "Start-GitLabMigration.cmd",
    "Clear-SavedTokens.cmd",
    "windows_bootstrap.py",
    "migration_wizard.py",
    "credential_store.py",
    "README-WINDOWS.txt",
    "MIGRATION-SCOPE.md",
    "SHA256SUMS",
)


class DistributionConfigurationError(RuntimeError):
    """社内配布設定または配布物の不正を表す。"""


def configure_console() -> None:
    """日本語を表示できるよう標準入出力のEncodingを調整する。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def validate_gitlab_url(value: str) -> str:
    """社内配布用GitLab URLを検証する。

    Args:
        value: 入力されたGitLab URL。

    Returns:
        末尾Slashを除いたHTTPS URL。

    Raises:
        DistributionConfigurationError: HTTPSの絶対URLでない場合。
    """
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise DistributionConfigurationError(
            "GitLab URLはhttps://から始まる絶対URLで指定してください"
        )
    if parsed.username or parsed.password:
        raise DistributionConfigurationError(
            "GitLab URLにユーザー名やPasswordを含めないでください"
        )
    if parsed.query or parsed.fragment:
        raise DistributionConfigurationError(
            "GitLab URLにQueryまたはFragmentを含めないでください"
        )
    if parsed.path.rstrip("/").endswith("/api/v4"):
        raise DistributionConfigurationError(
            "GitLab URLには/api/v4を含めないでください"
        )
    return normalized


def prompt_url(label: str, *, input_function: InputFunction = input) -> str:
    """有効なHTTPS URLが入力されるまで質問する。

    Args:
        label: 表示する項目名。
        input_function: 入力関数。Test時に差し替える。

    Returns:
        検証済みURL。
    """
    while True:
        value = input_function(f"{label}: ")
        try:
            return validate_gitlab_url(value)
        except DistributionConfigurationError as exc:
            print(f"  {exc}")


def prompt_required_free_gib(*, input_function: InputFunction = input) -> int:
    """必要空き容量を入力する。

    Args:
        input_function: 入力関数。Test時に差し替える。

    Returns:
        0以上のGiB値。
    """
    while True:
        value = input_function("必要な空き容量 GiB [50]: ").strip()
        if not value:
            return 50
        try:
            parsed = int(value)
        except ValueError:
            print("  数字で入力してください。")
            continue
        if parsed < 0:
            print("  0以上で入力してください。")
            continue
        return parsed


def build_settings(
    source_url: str,
    destination_url: str,
    required_free_gib: int,
) -> dict[str, object]:
    """社内配布用の秘密情報を含まない設定を作る。

    Args:
        source_url: 移行元GitLab URL。
        destination_url: 移行先GitLab URL。
        required_free_gib: Preflightで要求する空き容量。

    Returns:
        ウィザードが読み込む設定。

    Raises:
        DistributionConfigurationError: 容量が不正な場合。
    """
    if isinstance(required_free_gib, bool) or required_free_gib < 0:
        raise DistributionConfigurationError("必要な空き容量は0以上で指定してください")
    return {
        "source_gitlab_url": validate_gitlab_url(source_url),
        "destination_gitlab_url": validate_gitlab_url(destination_url),
        "required_free_gib": required_free_gib,
        "prompt_for_ca_bundle": False,
    }


def wheel_version(wheel: Path) -> str:
    """Wheel名からVersionを取得する。

    Args:
        wheel: 配布物に含まれるWheel。

    Returns:
        Wheel Version。

    Raises:
        DistributionConfigurationError: 想定外のWheel名の場合。
    """
    match = re.fullmatch(
        r"gitlab_group_migrator-([A-Za-z0-9_.!+-]+)-py3-none-any\.whl",
        wheel.name,
    )
    if match is None:
        raise DistributionConfigurationError(
            f"想定外の移行ツール本体です: {wheel.name}"
        )
    return match.group(1)


def _validate_settings_keys(settings: Mapping[str, object]) -> None:
    """設定にToken等の秘密情報がないことを確認する。

    Args:
        settings: ZIPへ保存する設定。

    Raises:
        DistributionConfigurationError: 許可外項目がある場合。
    """
    allowed = {
        "source_gitlab_url",
        "destination_gitlab_url",
        "required_free_gib",
        "prompt_for_ca_bundle",
    }
    unexpected = sorted(set(settings) - allowed)
    if unexpected:
        raise DistributionConfigurationError(
            f"社内配布設定に許可されていない項目があります: {unexpected}"
        )


def create_internal_bundle(
    public_bundle_directory: Path,
    output_directory: Path,
    settings: Mapping[str, object],
) -> tuple[Path, Path]:
    """公開配布物から実URL設定済みの社内専用ZIPを作る。

    Args:
        public_bundle_directory: 展開済み公開Windows配布Directory。
        output_directory: 社内専用ZIPの出力先。
        settings: 実URLを含む配布設定。

    Returns:
        社内専用ZIPとChecksumファイルのPath。

    Raises:
        DistributionConfigurationError: 配布物または設定が不正な場合。
    """
    public_bundle_directory = public_bundle_directory.resolve()
    _validate_settings_keys(settings)
    required_free_gib = settings.get("required_free_gib")
    if not isinstance(required_free_gib, int) or isinstance(required_free_gib, bool):
        raise DistributionConfigurationError(
            "必要な空き容量は0以上の整数で指定してください"
        )
    normalized_settings = build_settings(
        str(settings.get("source_gitlab_url") or ""),
        str(settings.get("destination_gitlab_url") or ""),
        required_free_gib,
    )
    try:
        wheel = windows_bootstrap.verify_wheel(public_bundle_directory)
    except windows_bootstrap.BootstrapError as exc:
        raise DistributionConfigurationError(str(exc)) from exc
    for filename in INTERNAL_RUNTIME_FILES:
        path = public_bundle_directory / filename
        if not path.is_file():
            raise DistributionConfigurationError(
                f"公開配布物に必要なファイルがありません: {filename}"
            )
    version = wheel_version(wheel)
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    bundle_name = f"gitlab-group-migrator-internal-v{version}"
    output_path = (
        output_directory.resolve() / f"{bundle_name}-{timestamp}.zip"
    )
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        for filename in INTERNAL_RUNTIME_FILES:
            archive.write(
                public_bundle_directory / filename,
                arcname=f"{bundle_name}/{filename}",
            )
        archive.write(wheel, arcname=f"{bundle_name}/{wheel.name}")
        archive.writestr(
            f"{bundle_name}/migration-settings.json",
            json.dumps(normalized_settings, ensure_ascii=False, indent=2) + "\n",
        )
    checksum_path = output_path.with_suffix(".zip.sha256")
    checksum_path.write_text(
        f"{windows_bootstrap.sha256(output_path)}  {output_path.name}\n",
        encoding="utf-8",
    )
    return output_path, checksum_path


def build_parser() -> argparse.ArgumentParser:
    """社内配布設定Toolの引数Parserを作成する。"""
    return argparse.ArgumentParser(
        description="GitLab URLをローカル入力し、社内専用Windows配布ZIPを作成"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """社内配布設定Toolを実行する。

    Args:
        argv: Command Line引数。

    Returns:
        Process終了Code。
    """
    configure_console()
    build_parser().parse_args(argv)
    bundle_directory = Path(__file__).resolve().parent
    print("実URLはGitHubや公開ファイルへ送信されません。")
    print("Access Tokenはここでは設定しません。\n")
    try:
        source_url = prompt_url("移行元GitLab URL")
        destination_url = prompt_url("移行先GitLab URL")
        required_free_gib = prompt_required_free_gib()
        settings = build_settings(
            source_url,
            destination_url,
            required_free_gib,
        )
        output, checksum = create_internal_bundle(
            bundle_directory,
            bundle_directory / "internal-distribution",
            settings,
        )
    except (DistributionConfigurationError, OSError) as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        return 2
    print("\n社内専用ZIPを作成しました。GitHubへUploadしないでください。")
    print(f"  ZIP: {output}")
    print(f"  Checksum: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
