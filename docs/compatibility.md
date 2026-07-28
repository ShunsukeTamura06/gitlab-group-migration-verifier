# 対応範囲

## 想定する移行方式

このツールはGitLabのGroup Export / Import APIとProject Export / Import APIを利用します。Direct Transferを利用できない環境で、Groupを先に作成し、Projectを対応するNamespaceへ配置します。

[GitLab公式のファイルImport互換範囲](https://docs.gitlab.com/user/project/settings/import_export/#compatibility)は、移行先から2 Minor Version以内です。開発時にはGitLab 15.3.3 EEをSource、GitLab 19.1.1 EEをDestinationとした移行を確認しましたが、この組み合わせは公式互換範囲外です。実機確認はGitLabの互換保証を置き換えません。実際のEdition、Patch Version、機能構成、データ量を使ったPilotと、移行責任者による例外承認が必要です。

## 自動移行・照合する項目

- Group / Subgroupの相対階層、Name、Path
- Group LabelとMilestone
- Group配下のProjectと相対Namespace
- ProjectのName、Path、Default Branch
- Repositoryが空か否か
- Export Archiveの形式、サイズ、SHA-256
- Project Importの完了状態と`failed_relations`

`failed_relations`の意味は[Project Import Status API](https://docs.gitlab.com/api/project_import_export/#retrieve-the-status-of-a-project-import)を参照してください。

VisibilityはSourceと一致しない場合に警告します。Destinationの管理設定やImport仕様によりPrivateへ変わることがあるため、受入確認で判断してください。

## 手動確認・再設定が必要な項目

- Members、継承権限、Group共有、招待
- Board、Badge、Wiki、Epic、Iteration
- CI/CD Variable、Webhook、Deploy Token、Group Access Token
- Runner、Push Rule、Branch Protection、SAML / LDAP連携
- Container Registry、Package Registry、LFS、大容量Repository
- 秘密情報、外部サービスとの接続情報

同名Group / Projectの自動統合、既存リソースの削除・上書き、途中停止後の自動Resumeには対応していません。

## VersionごとのExport内容

実際にExportされる項目はGitLab Versionによって変わります。SourceとDestinationそれぞれのGitLab Source Codeにある`project/import_export.yml`と`group/import_export.yml`を確認し、対象機能が含まれるかをPilot前に判断してください。
