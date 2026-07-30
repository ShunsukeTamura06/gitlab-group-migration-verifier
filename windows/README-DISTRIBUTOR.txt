GitLab Group Migrator - 社内配布担当者向け
==========================================

重要
----
- 実際のGitLab URLをGitHub、公開Issue、チャットへ投稿しないでください。
- Access Tokenは設定しません。利用者が実行時に非表示入力します。
- 生成した社内専用ZIPをGitHubへUploadしないでください。

社内専用ZIPの作り方
-------------------
1. GitHub ReleaseのWindows用ZIPを「すべて展開」します。
2. Configure-Distribution.cmdをダブルクリックします。
3. 移行元GitLab URL、移行先GitLab URL、必要な空き容量を入力します。
4. internal-distributionフォルダーに次の2ファイルが作成されます。
   - gitlab-group-migrator-internal-vX.Y.Z.zip
   - gitlab-group-migrator-internal-vX.Y.Z.zip.sha256
5. ZIPとChecksumを、承認済みの別経路で利用者へ配布します。

実URLの保存場所
--------------
実URLは生成した社内専用ZIP内のmigration-settings.jsonだけに保存されます。
公開ReleaseのZIP、Source Code、Git履歴には保存されません。
生成処理はURLをCommand Line引数へ渡さず、Shell履歴にも残しません。

社内CA
------
この配布設定では追加CAファイルを使用しません。
TLS接続に失敗した場合も証明書検証を無効化せず、社内IT部門へ連絡してください。

再配布前の確認
--------------
- MIGRATION-SCOPE.mdを同梱している
- 実URL以外の社内情報やTokenを追加していない
- ZIPのChecksumを配布経路とは別の承認済み経路で案内する
- Pilot用の移行申請と責任者が決まっている
