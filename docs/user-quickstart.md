# 利用者Quickstart

この手順は、移行責任者とGitLab管理者から承認済みの移行依頼を受けた実行担当者向けです。承認前に本番Groupを移行しないでください。

## Windowsで一番簡単に使う

### 1. 受領物を確認する

- `gitlab-group-migrator-windows-v1.2.0.zip`
- ZIPに同梱された`MIGRATION-SCOPE.md`
- 記入済みの[移行申請テンプレート](migration-request-template.md)
- Source / Destinationの短期Personal Access Token
- 社内CA Bundle（組織から指定された場合のみ）
- Export、Manifest、レポートの承認済み保存先

Tokenに必要な権限は、移行元が`api` scopeと対象GroupのOwner相当、移行先が`api` scopeとAdmin相当です。Tokenをチャット、チケット、メールで受け渡さないでください。

### 2. 移行対象・非対象を確認する

ZIPに同梱された`MIGRATION-SCOPE.md`を開き、次を移行責任者と確認します。

- 選択したGroupツリーだけが1回の実行対象である
- 自動移行・自動照合される項目
- GitLab標準Exportへ委ね、手動確認する項目
- 移行対象外として別途再設定する項目

対象外項目の再設定担当が決まっていない場合は開始しません。リポジトリ上の最新版は[移行対象・非対象](compatibility.md)です。

### 3. ZIPを展開して起動する

1. ZIPを右クリックし、「すべて展開」を選びます。
2. 展開したフォルダーを開きます。
3. `Start-GitLabMigration.cmd`をダブルクリックします。
4. Pythonがないと表示された場合は、Python 3.11以上をInstallしてからもう一度起動します。

初回だけ専用実行環境を自動作成します。PowerShellを開く、仮想環境を作る、`pip`を実行する操作は不要です。

### 4. 画面の質問に答える

次の順に入力します。

1. 移行元・移行先GitLabのURL
2. 移行元・移行先Access Token
3. 社内CAファイル（組織から渡された場合のみ）
4. 画面に表示された移行元Groupの番号
5. 「Pilot移行」「本番移行」「事前診断だけ」のいずれか
6. 移行先のGroup名とPath

Token入力中は文字も`*`も表示されませんが、入力されています。貼り付けてEnterを押してください。Tokenはファイルへ保存されません。

### 5. 最初は事前診断かPilotを選ぶ

ウィザードは、GitLabへ変更を加える前に必ずPreflightを実行します。

- 「失敗」があれば自動的に停止します。
- 「警告」があれば、移行責任者の判断を確認するまで進めません。
- 「事前診断だけ」ならGitLabへ変更を加えず終了します。
- 初回は小規模で代表的なGroupを使った「Pilot移行」を選びます。

### 6. 本番移行する

Pilotの受入確認、バックアップ、変更凍結、切り戻し手順、責任者承認が終わった後だけ「本番移行」を選びます。本番確認として画面に`PRODUCTION`と入力する必要があります。

終了コードが`0`でも、[受入確認チェックリスト](acceptance-checklist.md)の手動項目が完了するまで移行完了とはしません。

Manifestとレポートは、展開したフォルダー内の`work\manifests`と`work\reports`へ自動保存されます。

### 7. 失敗した場合

同じコマンドを再実行せず、[トラブルシューティング](troubleshooting.md)に従って情報を保存し、移行責任者へ連絡します。

## macOS / Linux・上級者向け

CLIのInstall、環境変数、Preflight、一括移行Commandは[README](../README.md)に記載しています。
