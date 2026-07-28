# トラブルシューティング

## 最初に行うこと

1. 同じ移行コマンドを再実行しない。
2. Sourceの変更凍結を維持する。
3. Destinationの作成済みGroup / Projectを削除しない。
4. Manifest、レポート、標準出力、標準エラーを保全する。

## 問い合わせ時に記録する情報

```bash
gitlab-migrator --version
```

- 発生日時とTimezone
- Source / Destination GitLab VersionとEdition
- Tokenを除いた実行コマンド
- 終了コード
- `preflight.json`
- Manifestの`state`、`error`、Group / Project ID
- Project Importの`correlation_id`、`import_error`、`failed_relations`
- Archive Path、Size、SHA-256

## 代表的な状態

### `failed_relations`がある

Project全体の`import_status`が`finished`でも部分的なRelation Import失敗です。成功として扱わず、Relation名、例外Class、例外Message、GitLab Server LogをGitLab管理者が確認します。

### Archive Size制限

Preflightの`max_import_size_mib`と`max_decompressed_archive_size_mib`を確認します。設定変更はGitLab管理者の承認済み作業として行い、Web Server側のUpload上限も確認します。

### Timeout

無条件にTimeoutを延長しません。Sidekiq、Gitaly、Disk、Database Timeout、対象データ量を確認し、原因を解消して新しいDestination Pathで再試行します。

### Destination Pathが存在する

既存Group / Projectは自動上書きしません。意図的な再利用でない限り別Pathを指定します。削除が必要な場合は、このツール外の承認済み手順で行います。

公開IssueへToken、社内URL、Export Archive、個人情報、Server Logを添付しないでください。連絡方法は[SUPPORT.md](../SUPPORT.md)を参照してください。
