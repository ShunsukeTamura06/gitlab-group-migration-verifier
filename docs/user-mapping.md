# ユーザーマッピング

GitLabのファイルImportでIssue、Merge Request、Comment等の作成者を正しく対応させるには、移行前のユーザー準備が必要です。

## 必須条件

- 必要なユーザーがDestinationに作成済みである。
- SourceユーザーのPublic Emailが設定されている。
- SourceのPublic Emailと、Destinationの確認済みPrimary Emailが一致する。
- Top-level Group Ownerまたは管理者がProjectをExportする。
- 管理者権限のTokenでImportする。

条件を満たさない場合、貢献履歴のユーザー関連付けがImport実行者へ置き換わる可能性があります。

## 実施手順

1. Source Group配下のDirect / Inherited Memberを一覧化する。
2. Username、氏名、Source Public Email、Destination Primary Email、Destination確認状態を照合表へ記録する。
3. 不一致、未確認、未作成のユーザーを解消する。
4. Pilotを実行し、代表的なIssue、Merge Request、Comment、Approval、Merged-byを確認する。
5. 不一致が残る場合は本番移行を開始しない。

メールアドレスやユーザー一覧は個人情報として扱い、公開Issueや公開リポジトリへ添付しないでください。
