"""初見のWindows利用者向けGitLab移行ウィザード。"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

InputFunction = Callable[[str], str]
SECRET_KEYS = ("SOURCE_GITLAB_TOKEN", "DESTINATION_GITLAB_TOKEN")
SETTINGS_FILENAME = "migration-settings.json"
ALLOWED_SETTINGS_KEYS = {
    "source_gitlab_url",
    "destination_gitlab_url",
    "required_free_gib",
    "prompt_for_ca_bundle",
}


class WizardError(RuntimeError):
    """利用者が修正可能なウィザードのエラーを表す。"""


def configure_console() -> None:
    """日本語を表示できるよう標準入出力のEncodingを調整する。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def prompt_required(
    label: str,
    *,
    default: str | None = None,
    input_function: InputFunction = input,
) -> str:
    """空文字を許可せず入力を受け取る。

    Args:
        label: 画面へ表示する項目名。
        default: Enter時に採用する初期値。
        input_function: 入力関数。Test時に差し替える。

    Returns:
        前後の空白を除いた入力値。
    """
    suffix = f" [{default}]" if default else ""
    while True:
        value = input_function(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default:
            return default
        print("  必須項目です。入力してください。")


def prompt_optional(
    label: str,
    *,
    input_function: InputFunction = input,
) -> str | None:
    """任意項目を入力する。

    Args:
        label: 画面へ表示する項目名。
        input_function: 入力関数。Test時に差し替える。

    Returns:
        入力値。空欄の場合はNone。
    """
    value = input_function(f"{label}（不要ならEnter）: ").strip()
    return value or None


def prompt_integer(
    label: str,
    *,
    default: int | None = None,
    minimum: int = 0,
    input_function: InputFunction = input,
) -> int:
    """指定範囲の整数を入力する。

    Args:
        label: 画面へ表示する項目名。
        default: Enter時に採用する初期値。
        minimum: 許可する最小値。
        input_function: 入力関数。Test時に差し替える。

    Returns:
        入力された整数。
    """
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input_function(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            print("  数字で入力してください。")
            continue
        if parsed < minimum:
            print(f"  {minimum}以上で入力してください。")
            continue
        return parsed


def prompt_yes_no(
    label: str,
    *,
    default: bool = False,
    input_function: InputFunction = input,
) -> bool:
    """Yes/Noの確認を行う。

    Args:
        label: 確認文。
        default: Enter時の選択。
        input_function: 入力関数。Test時に差し替える。

    Returns:
        Yesの場合True。
    """
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        value = input_function(f"{label}{suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("  y または n を入力してください。")


def safe_path_component(value: str) -> str:
    """成果物File名に使える文字列へ変換する。

    Args:
        value: Group Path等の文字列。

    Returns:
        安全なFile名要素。
    """
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return normalized or "migration"


def validate_url(value: str) -> str:
    """GitLab URLの最低限の形式を検査する。

    Args:
        value: 入力されたURL。

    Returns:
        末尾Slashを除いたURL。

    Raises:
        WizardError: HTTPS URLでもlocalhost URLでもない場合。
    """
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    is_local_http = (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1"}
    )
    if parsed.scheme != "https" and not is_local_http:
        raise WizardError("GitLab URLはhttps://から始めてください")
    if not parsed.netloc:
        raise WizardError("GitLab URLはHostを含む絶対URLで指定してください")
    if parsed.username or parsed.password:
        raise WizardError("GitLab URLにユーザー名やPasswordを含めないでください")
    if parsed.query or parsed.fragment:
        raise WizardError("GitLab URLにQueryまたはFragmentを含めないでください")
    if parsed.path.rstrip("/").endswith("/api/v4"):
        raise WizardError("GitLab URLには/api/v4を含めないでください")
    return normalized


def load_distribution_settings(bundle_directory: Path) -> dict[str, object] | None:
    """配布担当者が設定した接続先を読み込む。

    Args:
        bundle_directory: 展開済み社内配布Directory。

    Returns:
        検証済み設定。設定ファイルがない場合はNone。

    Raises:
        WizardError: 設定形式、URL、項目が不正な場合。
    """
    settings_path = bundle_directory / SETTINGS_FILENAME
    if not settings_path.exists():
        return None
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WizardError(
            f"{SETTINGS_FILENAME}を読み取れません。配布担当者へ連絡してください"
        ) from exc
    if not isinstance(payload, dict):
        raise WizardError(
            f"{SETTINGS_FILENAME}のルートはJSON Objectである必要があります"
        )
    unexpected = sorted(set(payload) - ALLOWED_SETTINGS_KEYS)
    if unexpected:
        raise WizardError(
            f"{SETTINGS_FILENAME}に許可されていない項目があります: {unexpected}"
        )
    source_url = payload.get("source_gitlab_url")
    destination_url = payload.get("destination_gitlab_url")
    required_free_gib = payload.get("required_free_gib")
    prompt_for_ca_bundle = payload.get("prompt_for_ca_bundle")
    if not isinstance(source_url, str) or not isinstance(destination_url, str):
        raise WizardError(f"{SETTINGS_FILENAME}にGitLab URLがありません")
    if (
        not isinstance(required_free_gib, int)
        or isinstance(required_free_gib, bool)
        or required_free_gib < 0
    ):
        raise WizardError(
            f"{SETTINGS_FILENAME}のrequired_free_gibは0以上の整数にしてください"
        )
    if not isinstance(prompt_for_ca_bundle, bool):
        raise WizardError(
            f"{SETTINGS_FILENAME}のprompt_for_ca_bundleはBooleanにしてください"
        )
    return {
        "source_gitlab_url": validate_url(source_url),
        "destination_gitlab_url": validate_url(destination_url),
        "required_free_gib": required_free_gib,
        "prompt_for_ca_bundle": prompt_for_ca_bundle,
    }


def parse_groups(output: str) -> list[dict[str, Any]]:
    """CLI出力から選択可能なGroup一覧を取り出す。

    Args:
        output: list-groupsのJSON出力。

    Returns:
        IDと表示名を持つGroup一覧。

    Raises:
        WizardError: JSON形式や必須項目が不正な場合。
    """
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise WizardError("移行元Group一覧の応答を読み取れません") from exc
    if not isinstance(payload, list):
        raise WizardError("移行元Group一覧の応答形式が不正です")
    groups = [
        item
        for item in payload
        if isinstance(item, dict)
        and isinstance(item.get("id"), int)
        and item.get("name")
        and item.get("full_path")
    ]
    if not groups:
        raise WizardError(
            "選択可能なGroupがありません。Access Tokenの権限を確認してください"
        )
    return groups


def choose_group(
    groups: Sequence[Mapping[str, Any]],
    *,
    heading: str = "移行元のGroupを選んでください。",
    input_function: InputFunction = input,
) -> Mapping[str, Any]:
    """番号入力で移行元Groupを選択する。

    Args:
        groups: 表示するGroup一覧。
        heading: 一覧の見出し。
        input_function: 入力関数。Test時に差し替える。

    Returns:
        選択されたGroup。
    """
    print(f"\n{heading}")
    for index, group in enumerate(groups, start=1):
        print(f"  {index:>3}. {group['full_path']} (ID: {group['id']})")
    while True:
        selected = prompt_integer(
            "番号",
            minimum=1,
            input_function=input_function,
        )
        if selected <= len(groups):
            return groups[selected - 1]
        print(f"  1から{len(groups)}の範囲で入力してください。")


def run_cli(
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
    bundle_directory: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Install済みCLIを同じPythonから実行する。

    Args:
        arguments: CLIへ渡す引数。
        environment: Tokenを含む子Process用環境変数。
        bundle_directory: 作業Directory。
        capture_output: 標準出力を捕捉するか。

    Returns:
        完了したProcess情報。
    """
    return subprocess.run(
        [sys.executable, "-m", "gitlab_migrator.cli", *arguments],
        cwd=bundle_directory,
        env=dict(environment),
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture_output,
    )


def run_cli_with_progress(
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
    bundle_directory: Path,
    heartbeat_seconds: float = 30,
) -> int:
    """長時間CLIを実行し、定期的に継続中であることを表示する。

    Args:
        arguments: CLIへ渡す引数。
        environment: Tokenを含む子Process用環境変数。
        bundle_directory: 作業Directory。
        heartbeat_seconds: 継続表示の間隔。

    Returns:
        子Processの終了Code。
    """
    process = subprocess.Popen(
        [sys.executable, "-m", "gitlab_migrator.cli", *arguments],
        cwd=bundle_directory,
        env=dict(environment),
        stdout=subprocess.DEVNULL,
    )
    try:
        while True:
            try:
                return process.wait(timeout=heartbeat_seconds)
            except subprocess.TimeoutExpired:
                now = datetime.now().astimezone().strftime("%H:%M:%S")
                print(f"  [{now}] 処理を継続しています。この画面を閉じないでください。")
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise


def print_process_error(label: str, process: subprocess.CompletedProcess[str]) -> None:
    """CLIの失敗内容を安全に表示する。

    Args:
        label: 失敗した処理名。
        process: 完了したProcess情報。
    """
    print(f"\n{label}に失敗しました。")
    if process.stderr:
        print(process.stderr.strip())


def show_preflight(result: Mapping[str, Any], output_path: Path) -> None:
    """Preflight結果の要点を表示する。

    Args:
        result: Preflight結果。
        output_path: 完全な結果を保存したPath。
    """
    labels = {"passed": "合格", "warning": "警告あり", "failed": "失敗"}
    print("\n事前診断結果")
    print(f"  判定: {labels.get(str(result.get('status')), result.get('status'))}")
    print(f"  移行元GitLab: {result.get('source_version') or '不明'}")
    print(f"  移行先GitLab: {result.get('destination_version') or '不明'}")
    failed_checks = [
        item
        for item in result.get("checks", [])
        if isinstance(item, dict) and item.get("status") == "failed"
    ]
    for item in failed_checks:
        print(f"  失敗: {item.get('name')} - {item.get('detail')}")
    for warning in result.get("warnings", []):
        print(f"  警告: {warning}")
    print(f"  詳細: {output_path}")


def select_mode(*, input_function: InputFunction = input) -> str:
    """実行Modeを選択する。

    Args:
        input_function: 入力関数。Test時に差し替える。

    Returns:
        pilot、production、preflightのいずれか。
    """
    print("\n実行内容を選んでください。")
    print("  1. Pilot移行（推奨: 本番前に小さなGroupで試す）")
    print("  2. 本番移行")
    print("  3. 事前診断だけ")
    selected = prompt_integer(
        "番号",
        default=1,
        minimum=1,
        input_function=input_function,
    )
    if selected not in {1, 2, 3}:
        print("  1から3の範囲で入力してください。")
        return select_mode(input_function=input_function)
    return {1: "pilot", 2: "production", 3: "preflight"}[selected]


def choose_destination_parent(
    *,
    environment: Mapping[str, str],
    bundle_directory: Path,
    input_function: InputFunction = input,
) -> str | None:
    """移行先の親GroupをRootまたは番号選択で決める。

    Args:
        environment: Tokenを含む子Process用環境変数。
        bundle_directory: 作業Directory。
        input_function: 入力関数。Test時に差し替える。

    Returns:
        選択した親Group ID。Root直下の場合はNone。

    Raises:
        WizardError: 移行先Group一覧を取得できない場合。
    """
    print("\n移行先の配置場所を選んでください。")
    print("  1. Root直下")
    print("  2. 既存の親Group配下")
    selected = prompt_integer(
        "番号",
        default=1,
        minimum=1,
        input_function=input_function,
    )
    if selected == 1:
        return None
    if selected != 2:
        raise WizardError("移行先の配置場所は1または2を選んでください")
    print("\n移行先からGroup一覧を取得しています...")
    process = run_cli(
        ["list-destination-groups"],
        environment=environment,
        bundle_directory=bundle_directory,
        capture_output=True,
    )
    if process.returncode != 0:
        print_process_error("移行先Group一覧の取得", process)
        raise WizardError("移行先Group一覧を取得できません")
    groups = parse_groups(process.stdout)
    parent = choose_group(
        groups,
        heading="移行先の親Groupを選んでください。",
        input_function=input_function,
    )
    return str(parent["id"])


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """JSON成果物を保存する。

    Args:
        path: 保存先。
        payload: 保存する内容。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def collect_environment(
    *,
    settings: Mapping[str, object] | None = None,
    input_function: InputFunction = input,
) -> dict[str, str]:
    """接続情報とTokenを対話入力から作る。

    Args:
        settings: 配布担当者が設定した接続先。未設定時は対話入力する。
        input_function: 通常項目の入力関数。

    Returns:
        子Process専用の環境変数。
    """
    environment = os.environ.copy()
    if settings is None:
        source_url = prompt_required("移行元GitLab URL", input_function=input_function)
        destination_url = prompt_required("移行先GitLab URL", input_function=input_function)
        environment["SOURCE_GITLAB_URL"] = validate_url(source_url)
        environment["DESTINATION_GITLAB_URL"] = validate_url(destination_url)
    else:
        environment["SOURCE_GITLAB_URL"] = str(settings["source_gitlab_url"])
        environment["DESTINATION_GITLAB_URL"] = str(
            settings["destination_gitlab_url"]
        )
        print("GitLab URLは配布担当者が設定済みです。画面やログへ表示しません。")
    print("\nTokenは画面に表示されず、ファイルにも保存されません。")
    environment["SOURCE_GITLAB_TOKEN"] = getpass.getpass(
        "移行元Access Token（api scope、Owner相当）: "
    ).strip()
    environment["DESTINATION_GITLAB_TOKEN"] = getpass.getpass(
        "移行先Access Token（api scope、Group作成・Import権限）: "
    ).strip()
    if not environment["SOURCE_GITLAB_TOKEN"] or not environment["DESTINATION_GITLAB_TOKEN"]:
        raise WizardError("Access Tokenは空にできません")
    prompt_for_ca_bundle = (
        settings is None or bool(settings.get("prompt_for_ca_bundle"))
    )
    if prompt_for_ca_bundle:
        source_ca = prompt_optional(
            "移行元の社内CAファイル",
            input_function=input_function,
        )
        destination_ca = prompt_optional(
            "移行先の社内CAファイル",
            input_function=input_function,
        )
    else:
        source_ca = None
        destination_ca = None
    if source_ca:
        environment["SOURCE_GITLAB_CA_BUNDLE"] = str(Path(source_ca).expanduser().resolve())
    else:
        environment.pop("SOURCE_GITLAB_CA_BUNDLE", None)
    if destination_ca:
        environment["DESTINATION_GITLAB_CA_BUNDLE"] = str(
            Path(destination_ca).expanduser().resolve()
        )
    else:
        environment.pop("DESTINATION_GITLAB_CA_BUNDLE", None)
    return environment


def execute_wizard(*, input_function: InputFunction = input) -> int:
    """対話式の事前診断と移行を実行する。

    Args:
        input_function: 通常項目の入力関数。

    Returns:
        Process終了Code。
    """
    bundle_directory = Path(__file__).resolve().parent
    settings = load_distribution_settings(bundle_directory)
    environment = collect_environment(
        settings=settings,
        input_function=input_function,
    )
    print("\n移行元からGroup一覧を取得しています...")
    group_process = run_cli(
        ["list-groups"],
        environment=environment,
        bundle_directory=bundle_directory,
        capture_output=True,
    )
    if group_process.returncode != 0:
        print_process_error("Group一覧の取得", group_process)
        return 2
    groups = parse_groups(group_process.stdout)
    selected_group = choose_group(groups, input_function=input_function)
    mode = select_mode(input_function=input_function)
    source_path = str(selected_group["full_path"])
    default_path = source_path.rsplit("/", maxsplit=1)[-1]
    if mode == "pilot":
        default_path = f"{default_path}-pilot"
    destination_name = prompt_required(
        "移行先Group名",
        default=str(selected_group["name"]),
        input_function=input_function,
    )
    destination_path = prompt_required(
        "移行先Group Path",
        default=default_path,
        input_function=input_function,
    )
    destination_parent = choose_destination_parent(
        environment=environment,
        bundle_directory=bundle_directory,
        input_function=input_function,
    )
    if settings is None:
        required_free_gib = prompt_integer(
            "必要な空き容量 GiB",
            default=50,
            minimum=0,
            input_function=input_function,
        )
    else:
        required_free_gib = int(settings["required_free_gib"])
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    artifact_name = safe_path_component(destination_path)
    preflight_path = (
        bundle_directory / "work" / "reports" / f"{artifact_name}-{timestamp}-preflight.json"
    )
    preflight_arguments = [
        "preflight",
        "--source-group-id",
        str(selected_group["id"]),
        "--destination-path",
        destination_path,
        "--required-free-gib",
        str(required_free_gib),
    ]
    if destination_parent:
        preflight_arguments.extend(["--destination-parent-id", destination_parent])
    print("\n変更を加えない事前診断を実行しています...")
    preflight_process = run_cli(
        preflight_arguments,
        environment=environment,
        bundle_directory=bundle_directory,
        capture_output=True,
    )
    if not preflight_process.stdout:
        print_process_error("事前診断", preflight_process)
        return 2
    try:
        preflight_result = json.loads(preflight_process.stdout)
    except json.JSONDecodeError as exc:
        raise WizardError("事前診断の応答を読み取れません") from exc
    if not isinstance(preflight_result, dict):
        raise WizardError("事前診断の応答形式が不正です")
    write_json(preflight_path, preflight_result)
    show_preflight(preflight_result, preflight_path)
    if preflight_process.returncode != 0 or preflight_result.get("status") == "failed":
        print("\n失敗項目を解決するまで移行は開始しません。")
        return 2
    if mode == "preflight":
        print("\n事前診断のみ完了しました。GitLabへの変更は行っていません。")
        return 0
    if preflight_result.get("status") == "warning":
        confirmation = input_function(
            "\n警告を責任者と確認済みなら CONTINUE と入力してください: "
        ).strip()
        if confirmation != "CONTINUE":
            print("移行を中止しました。GitLabへの変更は行っていません。")
            return 0
    if mode == "production":
        print(
            "\n本番移行には、Pilot成功、バックアップ、変更凍結、"
            "切り戻し手順、責任者承認が必要です。"
        )
        confirmation = input_function(
            "すべて完了している場合だけ PRODUCTION と入力してください: "
        ).strip()
        if confirmation != "PRODUCTION":
            print("本番移行を中止しました。")
            return 0
    elif not prompt_yes_no(
        "Pilot移行を開始しますか",
        default=False,
        input_function=input_function,
    ):
        print("Pilot移行を中止しました。")
        return 0
    manifest_path = (
        bundle_directory / "work" / "manifests" / f"{artifact_name}-{timestamp}.json"
    )
    report_path = (
        bundle_directory / "work" / "reports" / f"{artifact_name}-{timestamp}.md"
    )
    migration_arguments = [
        "--poll-interval",
        "20",
        "--timeout",
        "7200",
        "migrate-tree",
        "--source-group-id",
        str(selected_group["id"]),
        "--destination-name",
        destination_name,
        "--destination-path",
        destination_path,
        "--manifest",
        str(manifest_path),
    ]
    if destination_parent:
        migration_arguments.extend(["--destination-parent-id", destination_parent])
    print("\n移行を開始しました。規模により数時間かかることがあります。")
    migration_exit_code = run_cli_with_progress(
        migration_arguments,
        environment=environment,
        bundle_directory=bundle_directory,
    )
    if migration_exit_code != 0:
        print("\n移行は完了していません。同じ操作を再実行しないでください。")
        print(f"Manifestがあれば保全してください: {manifest_path}")
        return migration_exit_code
    report_process = run_cli(
        ["report", "--manifest", str(manifest_path), "--output", str(report_path)],
        environment=environment,
        bundle_directory=bundle_directory,
    )
    if report_process.returncode != 0:
        print(f"\n移行は終了しましたがレポート生成に失敗しました: {manifest_path}")
        return report_process.returncode
    print("\n移行処理と自動照合が完了しました。")
    print(f"  Manifest: {manifest_path}")
    print(f"  レポート: {report_path}")
    print("受入確認チェックリストの手動項目が終わるまで完了扱いにしないでください。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """ウィザードの引数Parserを作成する。"""
    return argparse.ArgumentParser(
        description="GitLab移行を画面の質問に答えて進めるWindows用ウィザード"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Windows移行ウィザードを実行する。

    Args:
        argv: Command Line引数。

    Returns:
        Process終了Code。
    """
    configure_console()
    build_parser().parse_args(argv)
    try:
        return execute_wizard()
    except KeyboardInterrupt:
        print("\n操作を中止しました。")
        return 130
    except (WizardError, OSError) as exc:
        print(f"\nエラー: {exc}", file=sys.stderr)
        return 2
    finally:
        for key in SECRET_KEYS:
            os.environ.pop(key, None)


if __name__ == "__main__":
    raise SystemExit(main())
