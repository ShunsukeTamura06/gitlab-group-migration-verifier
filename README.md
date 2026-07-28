# GitLab Group Migrator

GitLabのGroup階層と配下Projectを、ファイルExport / Importで旧環境から新環境へ移行するCLIです。Direct Transferを利用できない社内・閉域環境を想定し、事前診断、Archiveの安全性検査、移行後照合、Manifest、Markdownレポートまでを一つの手順で実行します。

> [!WARNING]
> GitLab公式のファイルImport互換範囲は、移行先から2 Minor Version以内です。開発時に確認した15.3.3 EEから19.1.1 EEへの移行は公式互換範囲外です。本ツールはこの組み合わせで実機確認していますが、移行成功や全データ保持を保証しません。必ず対象データと同等のPilot、バックアップ、変更凍結、切り戻し、移行責任者の承認を用意してください。

本ツールのRelease StatusはBetaです。各組織の移行手順全体を代替するものではありません。

## 主な機能

- Group / Subgroup階層、Label、MilestoneのExport / Import
- Group配下の全Project一括Export / Import
- 相対Namespaceに基づくProject配置
- 非同期Export / Importの待機、API timeout、指数バックオフ
- Archiveの形式、展開Path、サイズ、SHA-256検査
- 既存Group / Projectを上書きしない安全設計
- 接続、認証、Version、Project Import設定の非破壊Preflight
- Group階層とProjectのPath、Name、Default Branch、Repository状態の事後照合
- Project Import Status APIによる`failed_relations`検出
- 秘密情報をマスクしたManifestとMarkdownレポート
- SourceとDestinationへ同時接続できない環境向けの二段階移行

## 必要環境

- Python 3.11以上
- 移行元と移行先のGitLabへHTTPS接続できる端末
- 移行元: 対象GroupをExportできるOwner相当のPersonal Access Token
- 移行先: Group / Project ImportとApplication Settings確認に必要なAdmin相当のPersonal Access Token

ランタイム依存パッケージはありません。ユーザー名とパスワードによる認証、TLS検証の無効化、自動削除、自動上書きには対応していません。

## インストール

### Windows（推奨）

1. [v1.2.0 Release](https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/tag/v1.2.0)から`gitlab-group-migrator-windows-v1.2.0.zip`をDownloadします。
2. ZIPを右クリックして「すべて展開」を選びます。ZIP内から直接起動しないでください。
3. 展開先の`Start-GitLabMigration.cmd`をダブルクリックします。
4. 画面の質問に答え、最初は「Pilot移行」を選びます。

初回起動時にChecksum確認、専用仮想環境の作成、ツールのInstallを自動実行します。Access Tokenは画面に表示せず、ファイルにも保存しません。利用者によるPowerShell、環境変数、Group ID、`pip`、CLI Commandの操作は不要です。

Pythonがない場合だけ、[Python公式Windows版](https://www.python.org/downloads/windows/)からPython 3.11以上をInstallし、Python Launcherを有効にしてください。

### macOS / Linux・上級者向け

利用者は変更される`main`ではなく、[v1.2.0 Release](https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/tag/v1.2.0)のwheelをVersion固定で使用してください。

```bash
python3 -m venv .venv
. .venv/bin/activate

curl -LO \
  https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/download/v1.2.0/gitlab_group_migrator-1.2.0-py3-none-any.whl
curl -LO \
  https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/download/v1.2.0/SHA256SUMS

sha256sum --check --ignore-missing SHA256SUMS
python -m pip install ./gitlab_group_migrator-1.2.0-py3-none-any.whl
gitlab-migrator --version
```

macOSでwheelだけのチェックサムを確認する場合は`grep 'py3-none-any.whl' SHA256SUMS | shasum -a 256 -c -`を使用します。Gitから直接取得する場合もTagを固定します。

```bash
python -m pip install \
  'git+https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier.git@v1.2.0'
```

## 接続設定

Windows簡単スタートでは、画面の非表示入力欄へ移行元・移行先のTokenを貼り付けます。以下の環境変数設定はmacOS / Linuxおよび上級者向けです。Tokenは設定ファイルへ保存せず、Secrets Manager等から環境変数へ短時間だけ注入してください。

```bash
export SOURCE_GITLAB_URL='https://gitlab-old.internal.example'
export SOURCE_GITLAB_TOKEN='移行元のapi scope token'
export DESTINATION_GITLAB_URL='https://gitlab-new.internal.example'
export DESTINATION_GITLAB_TOKEN='移行先のapi scope token'

# 社内CAを使う場合
export SOURCE_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'
export DESTINATION_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'

# 大規模移行向けの例
export GITLAB_API_TIMEOUT=60
export GITLAB_API_MAX_RETRIES=4
```

まず、変更を加えない事前診断を実行します。

```bash
gitlab-migrator preflight \
  --source-group-id 123 \
  --destination-path engineering \
  --required-free-gib 50
```

必須チェックに失敗すると終了コード`2`、警告のみなら`0`です。警告は成功を意味しません。公式互換範囲外などの警告は、移行責任者がPilot結果とともに継続可否を記録してください。`gitlab_project` Import Sourceが無効な場合、GitLab管理者の承認後に`gitlab-migrator enable-project-import`で有効化できます。

## 一括移行

Group階層と配下の全Projectを移行します。

```bash
gitlab-migrator --poll-interval 20 --timeout 7200 migrate-tree \
  --source-group-id 123 \
  --destination-name engineering \
  --destination-path engineering \
  --manifest work/manifests/engineering-tree.json
```

完了後、Manifestから監査・受入確認用レポートを生成します。

```bash
gitlab-migrator report \
  --manifest work/manifests/engineering-tree.json \
  --output work/reports/engineering.md
```

同じPathがDestinationに存在すると、デフォルトで停止します。`--reuse-existing-group`は対象Groupを意図的に再利用する場合だけ指定してください。

## 二段階移行

SourceとDestinationへ同時接続できない場合は、ExportとImportを分けて実行します。

Sourceへ接続できる環境:

```bash
gitlab-migrator --poll-interval 20 --timeout 7200 export-tree \
  --source-group-id 123 \
  --manifest work/manifests/tree-123.json
```

Manifestと`work/exports`を承認済みの暗号化経路でDestination側へ搬送した後:

```bash
gitlab-migrator --poll-interval 20 --timeout 7200 import-tree \
  --manifest work/manifests/tree-123.json \
  --destination-name engineering \
  --destination-path engineering
```

`import-tree`はImport前に全Archiveの形式、サイズ、SHA-256を再確認し、Import後にGroup階層と全Projectを取り直して照合します。

## 対応範囲と注意事項

Membersの全Access Level、Board、Badge、Group Wiki、Epic、Iteration、Variable、Webhook、Deploy Token、Runner、Push Rule、招待、途中停止後の`--resume`は自動照合の対象外です。認証情報、Runner登録、Webhook等はExportで復元される前提にせず、事前棚卸しと再設定を行ってください。

実施前に次の順で確認してください。

1. [利用者Quickstart](docs/user-quickstart.md)
2. [移行申請テンプレート](docs/migration-request-template.md)
3. [ユーザーマッピング](docs/user-mapping.md)
4. [移行Runbook](docs/migration-runbook.md)
5. [受入確認チェックリスト](docs/acceptance-checklist.md)

詳細な対応範囲は[対応範囲](docs/compatibility.md)、失敗時は[トラブルシューティング](docs/troubleshooting.md)を参照してください。Exportアーカイブ、Manifest、レポートの取扱いは[セキュリティ方針](SECURITY.md)、問い合わせ方法は[SUPPORT.md](SUPPORT.md)に従ってください。

## ブランチ構成

- `main`: 利用者向けの本番移行CLI。GitLab検証コンテナやテストデータ生成機能は含みません。
- `develop`: 開発者向け。ローカルGitLab検証環境、検証データ生成、Smoke Test、実測記録を保持します。

検証環境を使う開発者は`develop`をCheckoutしてください。運用ルールは[開発ブランチ運用](DEVELOPMENT.md)に記載しています。

## ライセンス

[MIT License](LICENSE)
