# 社内GitLab移行Runbook

このRunbookは、Direct Transferを利用できない環境で、GitLab Group ExportとProject Exportを使った移行Pilotを安全に実施するための手順です。対象Versionは実機確認済みの15.3.3 EEから19.1.1 EEを基準にしています。

## 1. 実施判断と責任分界

作業開始前に、移行責任者、GitLab管理者、対象Group Owner、セキュリティ担当で次を合意します。

- 移行対象Group、Project、ユーザー、データ分類
- 変更凍結期間と最終差分の扱い
- Source / Destinationのバックアップと復元試験
- 許容停止時間、合否基準、切り戻し判断者
- Exportアーカイブ、Manifest、ログの保存先と保持期間
- このツールが未検証の機能と、手動補完する担当者

このツールはSourceを削除せず、Destinationの既存Group / Projectも自動削除・上書きしません。切り戻しはSourceを正として利用再開し、Destination側の新規リソースは承認後にGitLab管理者が別作業で処理します。

## 2. 移行前の棚卸し

最低限、次をAPIまたは管理画面から一覧化し、移行後の比較表を作成します。

- Group / Subgroup / ProjectのFull PathとVisibility
- Members、Group共有、招待、継承されたAccess Level
- Label、Milestone、Board、Badge、Wiki、Epic、Iteration
- Variable、Webhook、Deploy Token、Group Access Token
- Runner、Push Rule、Branch Protection、SAML / LDAP連携
- Container Registry、Package Registry、LFS、大容量Repository

Token、Variable値、Webhook Secret、Deploy Token、Runner Tokenは、Exportで安全に復元されると想定しないでください。Secrets Manager側の再発行・再設定手順を別に用意します。

## 3. 実行端末の準備

暗号化された管理端末または作業用VMを使用し、作業ディレクトリへのアクセスを担当者へ限定します。

```bash
umask 077
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
make all
```

Exportアーカイブは機密データとして扱います。ツールは生成ファイルを`0600`で保存しますが、ディスク、バックアップ、転送経路にも組織の暗号化基準を適用してください。

## 4. 認証と社内CA

実環境ではPassword Grantを使いません。Sourceは対象GroupをExportできるOwner相当のToken、DestinationはGroup / Project ImportとApplication Settingsを確認できるAdmin Tokenを、Secrets Managerから短時間だけ環境変数へ注入します。

```bash
export SOURCE_GITLAB_URL='https://gitlab-old.internal.example'
export SOURCE_GITLAB_TOKEN='...'
export DESTINATION_GITLAB_URL='https://gitlab-new.internal.example'
export DESTINATION_GITLAB_TOKEN='...'
export SOURCE_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'
export DESTINATION_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'
export GITLAB_API_TIMEOUT=60
export GITLAB_API_MAX_RETRIES=4
```

Shell履歴、CIログ、チケットへTokenを残さないでください。社内CAはPEM形式のBundleを指定します。TLS検証の無効化はできません。

## 5. 非破壊Preflight

```bash
gitlab-migrator preflight | tee preflight.json
```

次を確認します。

- Source / DestinationのVersion APIへ接続できる
- 両TokenでUser APIへ認証できる
- Destinationの`gitlab_project` Import Sourceが有効
- 作業ディレクトリへ書き込める
- URLがHTTPSである
- 実機検証済みVersionとの差異

`status: failed`は作業中止、`status: warning`は移行責任者が内容を確認して継続可否を記録します。`enable-project-import`はDestination設定を変更するため、Preflightから自動実行しません。

## 6. Pilot

本番Groupをいきなり移行せず、同じ機能構成を持つ小規模な検証Groupを別Pathへ移行します。

```bash
gitlab-migrator --poll-interval 20 --timeout 7200 migrate-tree \
  --source-group-id 10 \
  --destination-path pilot-migration-20260723 \
  --include-projects \
  --manifest work/manifests/pilot-tree.json
```

次を人手でも確認します。

- Group / Subgroup数と相対階層
- Project数、Repository、Default Branch、LFS
- Label / Milestone
- Membersと継承権限
- Issue / MR / Wiki / Epic / Iteration
- CI/CD Variable、Webhook、Runner、Registry

Manifestの`verification_status: failed`、Missing / Extra、想定外のFull Pathが1件でもあれば本番へ進みません。

## 7. 本番移行

1. Sourceの変更を凍結する。
2. Backup完了と復元可能性を確認する。
3. `preflight`を再実行する。
4. 競合しないDestination Pathを確認する。
5. `migrate-tree`を実行する。
6. ManifestとMarkdownレポートを保全する。
7. 棚卸し表で自動比較対象外を確認・補完する。
8. Ownerが受入確認を行う。
9. DNS、案内、権限切替等は別の承認済み手順で実施する。
10. Tokenを失効し、アーカイブを保持ポリシーに従って処理する。

実行例:

```bash
gitlab-migrator migrate-tree \
  --source-group-id 123 \
  --destination-name engineering \
  --destination-path engineering \
  --include-projects \
  --manifest work/manifests/engineering-tree.json

gitlab-migrator report \
  --manifest work/manifests/engineering-tree.json \
  --output work/reports/engineering.md
```

## 8. 失敗時

- 同じコマンドを無条件で再実行しない。
- Manifestの最後のState、作成済みDestination Group ID、Archive SHA-256を記録する。
- DestinationにGroup / Projectが作成済みなら、ツールは次回実行を停止する。
- 現Versionでは`--resume`が未実装のため、新しいDestination Pathで最初からやり直すか、管理者がManifestと実体を確認したうえで個別コマンドを使う。
- Destinationリソースの削除は、このツール外の承認済み手順で行う。
- Sourceの凍結解除または切り戻しは、移行責任者の判断後に行う。

## 9. 逐次実行が必要な閉域・低メモリ環境

SourceとDestinationへ同時接続できない場合は、自動`migrate-tree`を使わず二段階に分けます。

Source接続中:

```bash
gitlab-migrator --poll-interval 20 --timeout 7200 export-tree \
  --source-group-id 123 \
  --manifest work/manifests/tree-123.json
```

Destination接続へ切替後:

```bash
gitlab-migrator --poll-interval 20 --timeout 7200 import-tree \
  --manifest work/manifests/tree-123.json \
  --destination-name engineering \
  --destination-path engineering
```

`import-tree`は全ArchiveのサイズとSHA-256をImport前に再検証します。アーカイブを別Zoneへ搬送する場合は、暗号化、媒体管理、消去証跡も必須にします。

## 10. 採用条件

このツール単体の成功を、本番移行の成功とはみなしません。対象組織の全量データでPilotを行い、未検証機能の補完手順、性能、保存容量、監査証跡、切り戻しを含めて移行責任者が承認した場合にのみ採用します。
