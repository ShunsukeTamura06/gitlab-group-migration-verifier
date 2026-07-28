GitLab Group Migrator - Windows かんたんスタート
================================================

必要なもの
----------
- Windows 10 または 11
- Python 3.11以上
- 移行元と移行先のGitLabへ接続できるネットワーク
- 移行元のAccess Token（api scope、対象GroupのOwner相当）
- 移行先のAccess Token（api scope、Admin相当）
- 組織から指定された移行申請、バックアップ、承認

使い方
------
1. ZIP全体を右クリックし、「すべて展開」を選びます。
2. 展開したフォルダーの「Start-GitLabMigration.cmd」をダブルクリックします。
3. 画面の質問に答えます。最初は「Pilot移行」を選んでください。
4. 完了後、work\reports に作成されたレポートを責任者へ渡します。

Tokenについて
-------------
Tokenは入力時に画面へ表示されず、ファイルにも保存されません。
Tokenをチャット、チケット、メール、スクリーンショットへ載せないでください。

止めるべき場合
--------------
- 事前診断に「失敗」がある
- 警告について移行責任者の判断がない
- 本番前のPilot、バックアップ、変更凍結、切り戻し確認が終わっていない
- 途中でエラーになった（同じ操作をそのまま再実行しない）

詳細
----
https://github.com/ShunsukeTamura06/gitlab-group-migration-verifier
