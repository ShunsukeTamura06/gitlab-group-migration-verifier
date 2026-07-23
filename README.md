# GitLab Group Migration Verifier

GitLab 15.3.3 EEから19.1.1 EEへ、GroupとProjectをファイルExport / Importで移行し、Group階層・Label・Milestone・Project Namespaceを検証するCLIです。Direct Transferを利用できない社内環境での移行検証を主用途とします。

> [!WARNING]
> このVersion間の直接移行はGitLabの公式互換保証範囲外です。最小実機検証には成功していますが、全量移行の成功や全機能の保持を保証しません。必ず非本番データでPilotを行い、バックアップと変更承認を用意してください。

## 実装済み

- GitLab 15.3.3 / 19.1.1のローカルCompose検証環境
- Group Export、404 / 429を考慮したDownload待機、tar.gz安全性検査
- 既存Group / Projectを上書きしないImport
- Group階層、Label、Milestoneの比較
- 相対NamespaceマッピングによるProject配置
- Project Export / Importの非同期完了待機
- 秘密情報をマスクしたManifestとMarkdownレポート
- 接続、認証、Version、Project Import設定の非破壊Preflight
- 接続先別の社内CA Bundle、API timeout、指数バックオフ
- Export、Manifest、レポートの`0600`保存

2026-07-23に、Group、Subgroup、Label、Milestone、1 Projectの最小実機検証へ成功しました。根拠は[検証結果](docs/minimal-validation-2026-07-23.md)に記録しています。

## 未検証・非対応

Membersの全Access Level、Board、Badge、Group Wiki、Epic、Iteration、Variable、Webhook、Deploy Token、Runner、Push Rule、招待、同名競合、途中停止後の`--resume`、仕様にある完全なGroupツリーは未検証です。認証情報、Runner登録、Webhook等はExportアーカイブで復元される前提にせず、別途棚卸しと再設定を行ってください。

本番判断では、[社内移行Runbook](docs/internal-runbook.md)と[実装ステータス](docs/implementation-status.md)を確認してください。

## 必要環境

- Python 3.11以上
- 実環境のGitLabへHTTPS接続できる端末
- ローカル再現時のみDocker Desktop / Docker Compose v2、空きディスク約10GB

ランタイム依存パッケージはありません。

## インストール

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## 実環境の接続設定

Tokenはファイルへ保存せず、Secrets Manager等から環境変数へ注入してください。

```bash
export SOURCE_GITLAB_URL='https://gitlab-old.internal.example'
export SOURCE_GITLAB_TOKEN='移行元のapi scope token'
export DESTINATION_GITLAB_URL='https://gitlab-new.internal.example'
export DESTINATION_GITLAB_TOKEN='移行先のapi scope token'

# 社内CAを使う場合
export SOURCE_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'
export DESTINATION_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'
```

TLS検証を無効にするオプションはありません。移行元は対象GroupのOwner相当、移行先はGroup / Project ImportとApplication Settings確認に必要なAdmin権限を推奨します。

まず、変更を加えない事前診断を実行します。

```bash
gitlab-migrator preflight
```

必須チェックに失敗すると終了コード`2`、警告のみなら`0`です。

## 移行

Groupのみ:

```bash
gitlab-migrator migrate-group \
  --source-group-id 10 \
  --destination-path migration-destination \
  --exclude-projects
```

Groupを先に移行し、全Projectを対応Namespaceへ移行:

```bash
gitlab-migrator migrate-tree \
  --source-group-id 10 \
  --destination-path migration-destination \
  --include-projects
```

同じPathが移行先に存在すると、デフォルトで停止します。`--reuse-existing-group`は、そのGroupを意図的に使う場合だけ指定してください。自動削除や自動上書きは行いません。

## ローカル再現

```bash
cp .env.example .env
# .env内の2つのローカル用パスワードを変更
make up
make wait
```

- 移行元: http://localhost:8081
- 移行先: http://localhost:8082
- ユーザー名: `root`

GitLab 2台へ8GB以上のDockerメモリを推奨します。約4GBでは同時起動できないため、Sourceで`export-group` / `export-project` / `snapshot-group`を実行して停止し、Destinationへ切り替えてImport / Verifyする逐次方式を使います。

ローカルCompose環境に限り、Tokenの代わりに`SOURCE_GITLAB_ROOT_PASSWORD`と`DESTINATION_GITLAB_ROOT_PASSWORD`から一時OAuth Tokenを取得できます。実環境では使用しないでください。

## 開発と検証

```bash
make all
```

`make all`はCompileと単体テストだけを実行します。実GitLabを変更するSmoke Testは`make smoke-groups`として分離しています。

```bash
make down
```

Named Volumeは`make down`では削除されません。検証データを消去するMake targetは、誤消去防止のため提供していません。
