# Windows社内配布ガイド

この手順は、実際のGitLab URLを公開GitHubや利用者入力へ出さず、社内専用Windows ZIPを作成する配布担当者向けです。実URLをIssue、Pull Request、Source Code、会話へ記載しないでください。

## 公開Releaseから取得する

1. GitHub Releaseから`gitlab-group-migrator-windows-v1.2.2.zip`をDownloadします。
2. 公開Releaseの`SHA256SUMS`でZIPを検証します。
3. ZIPを右クリックし、「すべて展開」を選びます。

公開ZIPには無効な`.invalid`の例だけが含まれ、実際のGitLab URLは含まれません。

## 社内専用ZIPを作る

1. 展開先の`Configure-Distribution.cmd`をダブルクリックします。
2. 配布担当者のPC上で移行元GitLab URLを入力します。
3. 移行先GitLab URLを入力します。
4. Preflightで要求する空き容量をGiB単位で入力します。Enterなら50 GiBです。
5. `internal-distribution`フォルダーに作成されたZIPと`.sha256`を確認します。

入力したURLはCommand Line引数へ渡さず、Shell履歴やGit管理ファイルへ保存しません。実URLは生成した社内専用ZIP内の`migration-settings.json`だけに保存されます。

`migration-settings.json`はURL、必要容量、CA質問設定だけを許可します。Token、Password、Secret等の項目を追加するとウィザードは起動を拒否します。

## 配布前に確認する

- 社内専用ZIPをGitHubや公開ArtifactへUploadしない
- ZIPとChecksumを承認済みの別経路で利用者へ渡す
- Access TokenをZIPへ追加しない
- `MIGRATION-SCOPE.md`が同梱されている
- Pilot用移行申請、バックアップ、切り戻し、責任者を準備している

この組織では追加CAファイルを使用しないため、生成設定の`prompt_for_ca_bundle`は`false`です。TLS接続に失敗した場合も証明書検証を無効化せず、社内IT部門へ確認してください。

## 利用者へ伝えること

利用者は社内専用ZIPを展開し、`Start-GitLabMigration.cmd`をダブルクリックします。URL、社内CA、必要容量は質問されません。URLを質問された場合は公開汎用ZIPを誤って使用しているため、操作を中止して配布担当者へ連絡します。

利用者が入力するのはAccess Token、移行対象Group、実行Mode、移行先Group名とPathです。詳細は[利用者Quickstart](user-quickstart.md)を参照してください。
