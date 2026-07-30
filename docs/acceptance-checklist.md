# 受入確認チェックリスト

開始前に[移行対象・非対象](compatibility.md)を確認し、対象外項目の再設定結果もこの受入判断へ含めてください。

## 自動判定

- [ ] Manifestの`status`が`success`または承認済み`warning`
- [ ] Missing / Extra Groupが0件
- [ ] Missing / Extra Projectが0件
- [ ] Project Namespaceが全件一致
- [ ] `failed_relations`が0件
- [ ] ArchiveのSHA-256がManifestと一致

## 手動判定

- [ ] Group / Project Visibility
- [ ] Members、継承権限、Group共有、招待
- [ ] Issue、Merge Request、Comment、作成者、Approval
- [ ] Wiki、Board、Epic、Iteration
- [ ] Protected Branch / Tag、Push Rule
- [ ] CI/CD Variable、Pipeline Schedule、Webhook
- [ ] Runner、Deploy Token、Group / Project Access Token
- [ ] LFS、Container Registry、Package Registry
- [ ] 外部サービス、SAML / LDAP連携

## 承認

- Manifest:
- Markdown Report:
- 手動補完記録:
- 残存差分と受容理由:
- Group Owner:
- GitLab管理者:
- 移行責任者:
- 承認日時・Timezone:
