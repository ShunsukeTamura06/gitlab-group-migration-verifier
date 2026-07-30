"""GitLab Group移行CLI。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .client import GitLabClient
from .config import GitLabConfig
from .errors import GitLabApiError, MigratorError
from .group_exporter import GroupExporter
from .group_importer import GroupImporter
from .group_migrator import GroupMigrator
from .group_verifier import GroupVerifier
from .manifest import ManifestStore, redact_secrets
from .preflight import PreflightChecker
from .project_exporter import ProjectExporter
from .project_importer import ProjectImporter
from .project_verifier import ProjectTreeVerifier
from .report import write_markdown_report
from .tree_migrator import TreeBundleExporter, TreeBundleImporter, TreeMigrator

DEFAULT_EXPORT_DIR = Path("work/exports/groups")
DEFAULT_PROJECT_EXPORT_DIR = Path("work/exports/projects")
DEFAULT_MANIFEST_DIR = Path("work/manifests")
DEFAULT_REPORT_DIR = Path("work/reports")


def build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数Parserを生成する。"""
    parser = argparse.ArgumentParser(description="GitLabグループ移行ツール")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--poll-interval", type=float, default=5.0, help="ポーリング間隔（秒）")
    parser.add_argument("--timeout", type=float, default=600.0, help="処理タイムアウト（秒）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-groups", help="移行元のGroup一覧を表示")
    subparsers.add_parser(
        "list-destination-groups",
        help="移行先で選択可能な親Group一覧を表示",
    )
    preflight = subparsers.add_parser(
        "preflight",
        help="接続・認証・Import設定を非破壊で事前診断",
    )
    preflight.add_argument(
        "--required-free-gib",
        type=float,
        default=0,
        help="作業端末に必要な空き容量（GiB、0は容量判定なし）",
    )
    preflight.add_argument("--source-group-id", type=int)
    preflight.add_argument("--destination-path")
    preflight.add_argument("--destination-parent-id", type=int)
    subparsers.add_parser("import-settings", help="移行先のImport関連設定を表示")
    subparsers.add_parser(
        "enable-project-import", help="移行先でgitlab_project Import Sourceを有効化"
    )
    subparsers.add_parser("revoke-current-token", help="現在使用中の移行先PATを失効")
    list_subgroups = subparsers.add_parser("list-subgroups", help="移行先Group直下のSubgroup一覧")
    list_subgroups.add_argument("--destination-group-id", type=int, required=True)

    export = subparsers.add_parser("export-group", help="GroupをExport")
    export.add_argument("--source-group-id", type=int, required=True)
    export.add_argument("--output-dir", type=Path, default=DEFAULT_EXPORT_DIR)

    import_parser = subparsers.add_parser("import-group", help="GroupをImport")
    import_parser.add_argument("--archive", type=Path, required=True)
    import_parser.add_argument("--destination-name", required=True)
    import_parser.add_argument("--destination-path", required=True)
    import_parser.add_argument("--destination-parent-id", type=int)
    import_parser.add_argument("--reuse-existing-group", action="store_true")

    migrate = subparsers.add_parser("migrate-group", help="GroupをExport/Importして結果を照合")
    _add_migration_arguments(migrate)
    project_mode = migrate.add_mutually_exclusive_group()
    project_mode.add_argument("--exclude-projects", action="store_true", default=True)
    project_mode.add_argument(
        "--include-projects",
        action="store_true",
        help="Projectも含めてTree全体を移行（migrate-treeと同等）",
    )

    migrate_tree = subparsers.add_parser(
        "migrate-tree", help="Groupを先に移行し、配下Projectを対応Namespaceへ移行"
    )
    _add_migration_arguments(migrate_tree)
    tree_project_mode = migrate_tree.add_mutually_exclusive_group()
    tree_project_mode.add_argument("--include-projects", action="store_true", default=True)
    tree_project_mode.add_argument("--exclude-projects", action="store_true")

    export_tree = subparsers.add_parser(
        "export-tree",
        help="移行元からGroupと全Projectを一括Export",
    )
    export_tree.add_argument("--source-group-id", type=int, required=True)
    export_tree.add_argument("--manifest", type=Path)
    export_tree.add_argument("--exclude-projects", action="store_true")

    import_tree = subparsers.add_parser(
        "import-tree",
        help="Export済みTree Bundleを移行先へ一括Importして検証",
    )
    import_tree.add_argument("--manifest", type=Path, required=True)
    import_tree.add_argument("--destination-name")
    import_tree.add_argument("--destination-path", required=True)
    import_tree.add_argument("--destination-parent-id", type=int)
    import_tree.add_argument("--reuse-existing-group", action="store_true")

    verify = subparsers.add_parser("verify-group", help="Group階層とGroupデータを比較")
    _add_verification_arguments(verify)
    verify_tree = subparsers.add_parser(
        "verify-tree",
        help="Group階層と配下の全Projectを比較",
    )
    _add_verification_arguments(verify_tree)

    snapshot = subparsers.add_parser("snapshot-group", help="逐次移行用に移行元Groupを保存")
    snapshot.add_argument("--source-group-id", type=int, required=True)
    snapshot.add_argument("--output", type=Path, required=True)

    verify_snapshot = subparsers.add_parser(
        "verify-snapshot", help="保存済み移行元Snapshotと移行先Groupを比較"
    )
    verify_snapshot.add_argument("--source-snapshot", type=Path, required=True)
    verify_snapshot.add_argument("--destination-group-id", type=int, required=True)
    verify_snapshot.add_argument("--output", type=Path)

    export_project = subparsers.add_parser("export-project", help="ProjectをExport")
    export_project.add_argument("--source-project-id", type=int, required=True)
    export_project.add_argument("--output-dir", type=Path, default=DEFAULT_PROJECT_EXPORT_DIR)

    import_project = subparsers.add_parser("import-project", help="Projectを指定GroupへImport")
    import_project.add_argument("--archive", type=Path, required=True)
    import_project.add_argument("--destination-name", required=True)
    import_project.add_argument("--destination-path", required=True)
    import_project.add_argument("--destination-namespace-id", type=int, required=True)

    verify_project = subparsers.add_parser(
        "verify-project-placement", help="移行先ProjectのNamespace配置を確認"
    )
    verify_project.add_argument("--destination-project-id", type=int, required=True)
    verify_project.add_argument("--expected-full-path", required=True)
    wait_project = subparsers.add_parser(
        "wait-project-import", help="開始済みProject Importの完了を待機"
    )
    wait_project.add_argument("--destination-project-id", type=int, required=True)

    report = subparsers.add_parser("report", help="ManifestからMarkdownレポートを生成")
    report.add_argument("--source-group-id", type=int)
    report.add_argument("--manifest", type=Path)
    report.add_argument("--output", type=Path)
    return parser


def _add_migration_arguments(parser: argparse.ArgumentParser) -> None:
    """Group移行共通引数を追加する。"""
    parser.add_argument("--source-group-id", type=int, required=True)
    parser.add_argument("--destination-name")
    parser.add_argument("--destination-path", required=True)
    parser.add_argument("--destination-parent-id", type=int)
    parser.add_argument("--reuse-existing-group", action="store_true")
    parser.add_argument("--manifest", type=Path)


def _add_verification_arguments(parser: argparse.ArgumentParser) -> None:
    """Group検証共通引数を追加する。"""
    parser.add_argument("--source-group-id", type=int, required=True)
    parser.add_argument("--destination-group-id", type=int, required=True)
    parser.add_argument("--output", type=Path)


def source_client() -> GitLabClient:
    """環境変数から移行元クライアントを生成する。"""
    return _client_from_env("SOURCE")


def destination_client() -> GitLabClient:
    """環境変数から移行先クライアントを生成する。"""
    return _client_from_env("DESTINATION")


def _client_from_env(prefix: str) -> GitLabClient:
    """PATを使うGitLabクライアントを環境変数から作る。"""
    return GitLabClient(GitLabConfig.from_env(prefix))


def _list_available_groups(
    client: GitLabClient,
    *,
    owned: bool,
) -> list[dict[str, Any]]:
    """選択可能なGroupをGitLab Version互換の並び順で取得する。

    Args:
        client: Group一覧を取得するGitLab Client。
        owned: 明示的にOwnerであるGroupだけへ限定するか。

    Returns:
        `full_path`の昇順で並べたGroup一覧。
    """
    params = {"order_by": "path", "sort": "asc"}
    if owned:
        params["owned"] = "true"
    groups = client.list_all("/groups", params=params)
    return sorted(
        groups,
        key=lambda group: (
            str(
                group.get("full_path")
                or group.get("path")
                or group.get("name")
                or ""
            ).casefold(),
            group.get("id") if isinstance(group.get("id"), int) else 0,
        ),
    )


def run(args: argparse.Namespace) -> dict[str, Any] | list[Any]:
    """解析済み引数に対応する処理を実行する。"""
    if args.command == "list-groups":
        return _list_available_groups(source_client(), owned=True)
    if args.command == "list-destination-groups":
        return _list_available_groups(destination_client(), owned=False)
    if args.command == "preflight":
        if args.required_free_gib < 0:
            raise MigratorError("--required-free-gibは0以上で指定してください")
        return PreflightChecker(
            source_client(),
            destination_client(),
            required_free_bytes=int(args.required_free_gib * 1024**3),
        ).check(
            source_group_id=args.source_group_id,
            destination_path=args.destination_path,
            destination_parent_id=args.destination_parent_id,
        )
    if args.command == "import-settings":
        settings = destination_client().get_json("/application/settings")
        return {
            key: value
            for key, value in settings.items()
            if "import" in key
            or key
            in {
                "max_import_size",
                "max_export_size",
                "max_decompressed_archive_size",
                "decompress_archive_file_timeout",
            }
        }
    if args.command == "enable-project-import":
        response = destination_client().put_form(
            "/application/settings",
            {"import_sources[]": ["gitlab_project"]},
        ).json()
        return {"import_sources": response.get("import_sources")}
    if args.command == "revoke-current-token":
        destination_client().request(
            "DELETE", "/personal_access_tokens/self", expected={204}
        )
        return {"status": "revoked"}
    if args.command == "list-subgroups":
        return destination_client().list_all(
            f"/groups/{args.destination_group_id}/subgroups"
        )
    if args.command == "export-group":
        result = GroupExporter(
            source_client(),
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        ).export(args.source_group_id, args.output_dir)
        return result.to_dict()
    if args.command == "import-group":
        result = GroupImporter(
            destination_client(),
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        ).import_group(
            args.archive,
            name=args.destination_name,
            path=args.destination_path,
            parent_id=args.destination_parent_id,
            reuse_existing=args.reuse_existing_group,
        )
        from dataclasses import asdict

        return asdict(result)
    if args.command == "migrate-group":
        if args.include_projects:
            return _run_tree_migration(
                args,
                include_projects=True,
            )
        source = source_client()
        source_group = source.get_json(f"/groups/{args.source_group_id}")
        destination_name = args.destination_name or str(source_group.get("name", args.destination_path))
        manifest_path = args.manifest or DEFAULT_MANIFEST_DIR / f"group-{args.source_group_id}.json"
        return GroupMigrator(
            source,
            destination_client(),
            export_dir=DEFAULT_EXPORT_DIR,
            manifest_path=manifest_path,
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        ).migrate(
            args.source_group_id,
            destination_name=destination_name,
            destination_path=args.destination_path,
            destination_parent_id=args.destination_parent_id,
            reuse_existing=args.reuse_existing_group,
        )
    if args.command == "migrate-tree":
        return _run_tree_migration(
            args,
            include_projects=not args.exclude_projects,
        )
    if args.command == "export-tree":
        manifest_path = (
            args.manifest
            or DEFAULT_MANIFEST_DIR / f"tree-{args.source_group_id}.json"
        )
        return TreeBundleExporter(
            source_client(),
            group_export_dir=DEFAULT_EXPORT_DIR,
            project_export_dir=DEFAULT_PROJECT_EXPORT_DIR,
            manifest_path=manifest_path,
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        ).export(
            args.source_group_id,
            include_projects=not args.exclude_projects,
        )
    if args.command == "import-tree":
        manifest = ManifestStore(args.manifest).load()
        source_snapshot = (manifest.get("source") or {}).get("group_snapshot")
        if not isinstance(source_snapshot, dict):
            raise MigratorError("Tree Manifestに移行元Group Snapshotがありません")
        source_root = next(
            node
            for node in GroupVerifier.snapshot_nodes(source_snapshot)
            if node.relative_path == "."
        )
        return TreeBundleImporter(
            destination_client(),
            manifest_path=args.manifest,
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        ).import_bundle(
            destination_name=args.destination_name or source_root.name,
            destination_path=args.destination_path,
            destination_parent_id=args.destination_parent_id,
            reuse_existing_group=args.reuse_existing_group,
        )
    if args.command == "verify-group":
        result = GroupVerifier(source_client(), destination_client()).verify(
            args.source_group_id, args.destination_group_id
        )
        payload = result.to_dict()
        if args.output:
            ManifestStore(args.output).save(payload)
        return payload
    if args.command == "verify-tree":
        source = source_client()
        destination = destination_client()
        group_result = GroupVerifier(source, destination).verify(
            args.source_group_id,
            args.destination_group_id,
        )
        project_result = ProjectTreeVerifier.verify(
            source,
            destination,
            args.source_group_id,
            args.destination_group_id,
        )
        if project_result.status == "failed":
            status = "failed"
        elif group_result.status == "warning" or project_result.status == "warning":
            status = "warning"
        else:
            status = "success"
        payload = {
            "status": status,
            "group_verification": group_result.to_dict(),
            "project_verification": project_result.to_dict(),
        }
        if args.output:
            ManifestStore(args.output).save(payload)
        return payload
    if args.command == "snapshot-group":
        payload = GroupVerifier.capture(source_client(), args.source_group_id)
        ManifestStore(args.output).save(payload)
        return {"status": "finished", "snapshot_path": str(args.output), **payload}
    if args.command == "verify-snapshot":
        source_snapshot = ManifestStore(args.source_snapshot).load()
        destination = destination_client()
        result = GroupVerifier(destination, destination).verify_snapshot(
            source_snapshot,
            args.destination_group_id,
        )
        payload = result.to_dict()
        if args.output:
            ManifestStore(args.output).save(payload)
        return payload
    if args.command == "export-project":
        return ProjectExporter(
            source_client(),
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        ).export(args.source_project_id, args.output_dir).to_dict()
    if args.command == "import-project":
        from dataclasses import asdict

        return asdict(
            ProjectImporter(
                destination_client(),
                poll_interval_seconds=args.poll_interval,
                timeout_seconds=args.timeout,
            ).import_project(
                args.archive,
                name=args.destination_name,
                path=args.destination_path,
                namespace_id=args.destination_namespace_id,
            )
        )
    if args.command == "verify-project-placement":
        client = destination_client()
        project = client.get_json(f"/projects/{args.destination_project_id}")
        actual = str(project.get("path_with_namespace"))
        repository_tree = client.get_json(
            f"/projects/{args.destination_project_id}/repository/tree",
            params={"per_page": 1},
        )
        return {
            "status": "success" if actual == args.expected_full_path else "failed",
            "project_id": args.destination_project_id,
            "expected_full_path": args.expected_full_path,
            "actual_full_path": actual,
            "namespace_match": actual == args.expected_full_path,
            "default_branch": project.get("default_branch"),
            "repository_non_empty": isinstance(repository_tree, list) and bool(repository_tree),
        }
    if args.command == "wait-project-import":
        project = ProjectImporter(
            destination_client(),
            poll_interval_seconds=args.poll_interval,
            timeout_seconds=args.timeout,
        ).wait_for_import(args.destination_project_id)
        return {
            "status": "finished",
            "project_id": project.get("id"),
            "full_path": project.get("path_with_namespace"),
            "import_status": project.get("import_status"),
            "import_error": project.get("import_error"),
        }
    if args.command == "report":
        if args.manifest is None and args.source_group_id is None:
            raise MigratorError("--manifestまたは--source-group-idを指定してください")
        manifest_path = args.manifest or DEFAULT_MANIFEST_DIR / f"group-{args.source_group_id}.json"
        output = args.output or DEFAULT_REPORT_DIR / f"group-{args.source_group_id or 'report'}.md"
        manifest = ManifestStore(manifest_path).load()
        write_markdown_report(manifest, output)
        return {"status": "finished", "report_path": str(output)}
    raise AssertionError(f"未処理のコマンドです: {args.command}")


def _run_tree_migration(
    args: argparse.Namespace,
    *,
    include_projects: bool,
) -> dict[str, Any]:
    """SourceとDestinationへ接続してTree移行を一括実行する。"""
    source = source_client()
    source_group = source.get_json(f"/groups/{args.source_group_id}")
    destination_name = args.destination_name or str(
        source_group.get("name", args.destination_path)
    )
    manifest_path = (
        args.manifest
        or DEFAULT_MANIFEST_DIR / f"tree-{args.source_group_id}.json"
    )
    return TreeMigrator(
        source,
        destination_client(),
        group_export_dir=DEFAULT_EXPORT_DIR,
        project_export_dir=DEFAULT_PROJECT_EXPORT_DIR,
        manifest_path=manifest_path,
        poll_interval_seconds=args.poll_interval,
        timeout_seconds=args.timeout,
    ).migrate(
        args.source_group_id,
        destination_name=destination_name,
        destination_path=args.destination_path,
        destination_parent_id=args.destination_parent_id,
        include_projects=include_projects,
        reuse_existing_group=args.reuse_existing_group,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLIエントリーポイント。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (MigratorError, OSError, ValueError) as exc:
        detail = ""
        if isinstance(exc, GitLabApiError) and exc.body:
            try:
                safe_body = json.dumps(
                    redact_secrets(json.loads(exc.body)), ensure_ascii=False
                )
            except json.JSONDecodeError:
                safe_body = exc.body
            detail = f" response={safe_body}"
        print(f"error: {exc}{detail}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if (
        args.command
        in {"preflight", "verify-group", "verify-tree", "verify-project-placement"}
        and isinstance(result, dict)
        and result.get("status") == "failed"
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
