# GitLab Group Migrator

GitLabのGroup階層と配下Projectを、ファイルExport / Importで旧環境から新環境へ移行するCLIです。Direct Transferを利用できない社内・閉域環境を想定し、事前診断、Archiveの安全性検査、移行後照合、Manifest、Markdownレポートまでを一つの手順で実行します。

> [!WARNING]
> GitLab公式のファイルImport互換範囲は、移行先から2 Minor Version以内です。開発時に確認した15.3.3 EEから19.1.1 EEへの移行は公式互換範囲外です。本ツールはこの組み合わせで実機確認していますが、移行成功や全データ保持を保証しません。必ず対象データと同等のPilot、バックアップ、変更凍結、切り戻し、移行責任者の承認を用意してください。

本ツールのRelease StatusはBetaです。各組織の移行手順全体を代替するものではありません。

> [!IMPORTANT]
> 移行前に[移行対象・非対象](docs/compatibility.md)を確認してください。選択したGroupツリーは一括移行しますが、GitLab Instance全体、共有Project、ユーザーアカウント、Secret、Token、Runner、Registry等は対象外です。GitLab標準Exportへ委ねる項目には手動確認が必要です。

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

### Windows社内配布（推奨）

配布担当者:

1. [v1.2.1 Release](https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/tag/v1.2.1)から公開Windows ZIPを取得します。
2. ZIPを展開し、`Configure-Distribution.cmd`をダブルクリックします。
3. 配布担当者のPCだけで実際の移行元・移行先URLを入力します。
4. 生成された社内専用ZIPとChecksumを承認済み経路で配布します。

実URLはGitHub、Source Code、Command Line引数、Shell履歴へ保存しません。Access Tokenも社内専用ZIPへ含めません。詳細は[Windows社内配布ガイド](docs/distributor-guide.md)を参照してください。

利用者:

1. 社内配布担当者から受領したZIPを「すべて展開」します。
2. `MIGRATION-SCOPE.md`で移行対象・非対象を確認します。
3. `Start-GitLabMigration.cmd`をダブルクリックします。
4. Access Tokenを非表示入力し、Groupと実行Modeを番号で選びます。

利用者へGitLab URL、社内CA、必要容量は質問しません。質問された場合は公開汎用ZIPを誤って使用しているため、操作を中止します。初回起動時にChecksum確認、専用仮想環境の作成、ツールのInstallを自動実行します。

配布担当者と利用者のPCにPythonがない場合だけ、[Python公式Windows版](https://www.python.org/downloads/windows/)からPython 3.11以上をInstallし、Python Launcherを有効にしてください。

### macOS / Linux・上級者向け

利用者は変更される`main`ではなく、[v1.2.1 Release](https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/tag/v1.2.1)のwheelをVersion固定で使用してください。

```bash
python3 -m venv .venv
. .venv/bin/activate

curl -LO \
  https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/download/v1.2.1/gitlab_group_migrator-1.2.1-py3-none-any.whl
curl -LO \
  https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier/releases/download/v1.2.1/SHA256SUMS

sha256sum --check --ignore-missing SHA256SUMS
python -m pip install ./gitlab_group_migrator-1.2.1-py3-none-any.whl
gitlab-migrator --version
```

macOSでwheelだけのチェックサムを確認する場合は`grep 'py3-none-any.whl' SHA256SUMS | shasum -a 256 -c -`を使用します。Gitから直接取得する場合もTagを固定します。

```bash
python -m pip install \
  'git+https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier.git@v1.2.1'
```

## 接続設定

Windows社内専用ZIPではGitLab URLが配布担当者により設定済みで、利用者は画面の非表示入力欄へ移行元・移行先のTokenだけを貼り付けます。以下の環境変数設定はmacOS / Linuxおよび上級者向けです。Tokenは設定ファイルへ保存せず、Secrets Manager等から環境変数へ短時間だけ注入してください。

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

1. [Windows社内配布ガイド](docs/distributor-guide.md)
2. [利用者Quickstart](docs/user-quickstart.md)
3. [移行申請テンプレート](docs/migration-request-template.md)
4. [ユーザーマッピング](docs/user-mapping.md)
5. [移行Runbook](docs/migration-runbook.md)
6. [受入確認チェックリスト](docs/acceptance-checklist.md)

詳細な対応範囲は[対応範囲](docs/compatibility.md)、失敗時は[トラブルシューティング](docs/troubleshooting.md)を参照してください。Exportアーカイブ、Manifest、レポートの取扱いは[セキュリティ方針](SECURITY.md)、問い合わせ方法は[SUPPORT.md](SUPPORT.md)に従ってください。

## ブランチ構成

- `main`: 利用者向けの本番移行CLI。GitLab検証コンテナやテストデータ生成機能は含みません。
- `develop`: 開発者向け。ローカルGitLab検証環境、検証データ生成、Smoke Test、実測記録を保持します。

検証環境を使う開発者は`develop`をCheckoutしてください。運用ルールは[開発ブランチ運用](DEVELOPMENT.md)に記載しています。

## ライセンス

[MIT License](LICENSE)
