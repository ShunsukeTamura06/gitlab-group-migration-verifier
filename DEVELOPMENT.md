# 開発ブランチ運用

このリポジトリは、利用者向け配布物とGitLab実機検証環境を長期ブランチで分離します。

## ブランチ

- `main`: 本番移行機能と単体テスト。利用者へ配布する唯一の基準ブランチ。
- `develop`: `main`の機能に、Docker ComposeのGitLab検証環境、検証データ生成CLI、Smoke Test、実測記録を加えた開発ブランチ。

## 変更の流れ

1. 本番コードの修正は`main`向けの作業ブランチで実装し、単体テスト後にPull Requestを作成する。
2. `main`へMergeした本番コードは、`develop`へMergeまたはCherry-pickして検証環境へ反映する。
3. 検証環境、Fixture、Smoke Testだけの変更は`develop`へPull Requestを作成する。
4. `develop`で確認した本番コードを`main`へ戻す場合は、検証専用ファイルを含めず、本番コードと単体テストだけを対象にする。
5. Release tagは`main`のCommitにだけ付ける。

`main`へDocker Compose、ローカルrootパスワード認証、テストデータ生成コマンド、実測ログをMergeしないでください。

## ローカル品質確認

```bash
make all
```

これはCompileと単体テストを実行します。GitLab実機を変更する検証は`develop`でのみ実行します。
