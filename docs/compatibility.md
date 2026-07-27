# 対応範囲

## 想定する移行方式

このツールはGitLabのGroup Export / Import APIとProject Export / Import APIを利用します。Direct Transferを利用できない環境で、Groupを先に作成し、Projectを対応するNamespaceへ配置します。

開発時にはGitLab 15.3.3 EEをSource、GitLab 19.1.1 EEをDestinationとした移行を確認しています。ただし、GitLabがこのVersion間のファイルImportをすべてのデータ種別について保証することを意味しません。実際のEdition、Patch Version、機能構成、データ量を使ったPilotが必要です。

## 自動移行・照合する項目

- Group / Subgroupの相対階層、Name、Path
- Group LabelとMilestone
- Group配下のProjectと相対Namespace
- ProjectのName、Path、Default Branch
- Repositoryが空か否か
- Export Archiveの形式、サイズ、SHA-256

VisibilityはSourceと一致しない場合に警告します。Destinationの管理設定やImport仕様によりPrivateへ変わることがあるため、受入確認で判断してください。

## 手動確認・再設定が必要な項目

- Members、継承権限、Group共有、招待
- Board、Badge、Wiki、Epic、Iteration
- CI/CD Variable、Webhook、Deploy Token、Group Access Token
- Runner、Push Rule、Branch Protection、SAML / LDAP連携
- Container Registry、Package Registry、LFS、大容量Repository
- 秘密情報、外部サービスとの接続情報

同名Group / Projectの自動統合、既存リソースの削除・上書き、途中停止後の自動Resumeには対応していません。
