# 利用者Quickstart

この手順は、移行責任者とGitLab管理者から承認済みの移行依頼を受けた実行担当者向けです。承認前に本番Groupを移行しないでください。

## 1. 受領物を確認する

- `gitlab_group_migrator-1.1.0-py3-none-any.whl`
- `SHA256SUMS`
- 記入済みの[移行申請テンプレート](migration-request-template.md)
- Source / Destinationの短期Personal Access Token
- 社内CA Bundle
- Export、Manifest、レポートの承認済み保存先

## 2. インストールする

```bash
sha256sum --check --ignore-missing SHA256SUMS
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./gitlab_group_migrator-1.1.0-py3-none-any.whl
gitlab-migrator --version
```

## 3. 接続情報を設定する

```bash
export SOURCE_GITLAB_URL='https://gitlab-old.internal.example'
export SOURCE_GITLAB_TOKEN='...'
export DESTINATION_GITLAB_URL='https://gitlab-new.internal.example'
export DESTINATION_GITLAB_TOKEN='...'
export SOURCE_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'
export DESTINATION_GITLAB_CA_BUNDLE='/secure/path/corporate-ca.pem'
```

Tokenをファイル、Shell履歴、チケットへ貼り付けないでください。

## 4. Preflightを実行する

```bash
gitlab-migrator preflight \
  --source-group-id 123 \
  --destination-path engineering \
  --required-free-gib 50 \
  | tee preflight.json
```

`failed`があれば中止します。`warning`は移行責任者が理由と継続判断を記録するまで先へ進みません。

## 5. Pilot後に本番移行する

```bash
gitlab-migrator --poll-interval 20 --timeout 7200 migrate-tree \
  --source-group-id 123 \
  --destination-name engineering \
  --destination-path engineering \
  --manifest work/manifests/engineering-tree.json

gitlab-migrator report \
  --manifest work/manifests/engineering-tree.json \
  --output work/reports/engineering.md
```

終了コードが`0`でも、[受入確認チェックリスト](acceptance-checklist.md)の手動項目が完了するまで移行完了とはしません。

## 6. 失敗した場合

同じコマンドを再実行せず、[トラブルシューティング](troubleshooting.md)に従って情報を保存し、移行責任者へ連絡します。
