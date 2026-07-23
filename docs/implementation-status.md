# 実装・検証ステータス

## Phase 1: Group最小検証

- [x] APIクライアント
- [x] Group Export / Downloadポーリング
- [x] Group Import / Import後Group解決
- [x] Group階層正規化
- [x] Label / Milestone比較
- [x] Namespaceマッピング
- [x] Manifest / Report
- [x] 単体テスト
- [x] GitLab 15.3.3での実API検証
- [x] GitLab 19.1.1への実Import検証
- [x] Subgroup / Label / Milestoneの実比較

## Phase 2: Project統合

- [x] Group配下へ1 ProjectをImport
- [x] Namespace配置確認
- [ ] 全Project移行
- [ ] Group / Project関連性比較
- [x] `make migrate-tree`の有効化

## 既知の環境制約

現在のDocker Desktop割当は4 CPU、約3.8GiBです。GitLab 2台の同時起動には不足する可能性があるため、OOM発生時は逐次起動方式に切り替えます。

実測では19.1.1単体が約2.9GiB、15.3.3単体が約2.0GiBを使用し、2台同時起動時にDocker APIが無応答になりました。最小検証は逐次起動方式で完了しています。

## Phase 3: 追加Groupデータと異常系

- [ ] Members（各Access Level、継承、ユーザー不足）
- [ ] Board / Badge / Wiki / Epic / Iteration
- [ ] Variable / Webhook / Deploy Tokenなど対象外項目
- [ ] 途中停止後の`--resume`
- [ ] 完全なテスト用Groupツリー
- [ ] 実機での全Project統合移行

## 社内利用向けHardening

- [x] 非破壊Preflight
- [x] 社内CA Bundle対応（TLS検証は常時有効）
- [x] 固定パスワードのComposeフォールバック廃止
- [x] APIエラー内Tokenのマスク
- [x] Export / Manifest / Reportの`0600`保存
- [x] 社内移行RunbookとSecurityガイド
- [x] Python 3.11 / 3.12 / 3.13のCI
- [ ] 途中停止後の安全な`--resume`
- [ ] 全機能・全量データでの本番相当Pilot
