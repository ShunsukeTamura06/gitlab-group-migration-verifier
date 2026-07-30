# 移行対象・非対象

> [!IMPORTANT]
> 本ツールの実行成功は、GitLab全データの移行完了を意味しません。自動照合対象、手動確認対象、別途再設定する対象を区別し、Pilotと受入確認を完了してから本番移行してください。

## 1回の実行で選択する範囲

Windowsウィザードでは、次のどちらかを1回の実行単位として選びます。

1. 移行元で選択した1つのGroupツリー
2. 移行元Token利用者の個人Namespace直下にある全Project

Groupツリー移行には次が含まれます。

- 選択したRoot Group
- Root Group配下のすべてのSubgroup
- Root Groupと各Subgroupが所有するすべてのProject
- GitLab APIが一覧へ返すArchived Projectと空RepositoryのProject

対象に含まれません。

- 選択したGroupツリー外のGroupとProject
- 別のTop-level Group
- Personal NamespaceのProject（個人Project一括移行を選んだ場合は対象）
- 対象Groupへ共有されているだけのProject

複数の独立したTop-level Groupを移行する場合は、Groupごとに実行します。本ツールはGitLab Instance全体を1回で移行するものではありません。

個人Project一括移行では、移行元Token利用者の個人Namespace直下だけを列挙し、移行先Token利用者の個人Namespace直下へ同じProject PathでImportします。他ユーザーの個人ProjectとGroup配下Projectは含めません。移行先に同じPathが1件でも存在する場合は、変更前の事前診断で停止します。

> [!WARNING]
> GitLabの個人NamespaceへのImportではユーザー投稿者マッピングを保持できません。Issue、Merge Request、Comment等の投稿者は移行先の個人Namespace所有者へ集約され、後から再割り当てできません。

## 自動移行・自動照合する項目

本ツールがGitLabのGroup Export / Import APIとProject Export / Import APIを呼び出し、移行後に自動照合する項目です。

- Group / Subgroupの相対階層、Name、Path
- Group LabelとMilestone
- Group配下のProject数と相対Namespace
- ProjectのName、Path、Default Branch
- Repositoryが空か否か
- ProjectのDescription、Visibility、Archived状態の差異
- Export Archiveの形式、サイズ、SHA-256
- Project Importの完了状態と`failed_relations`

ProjectのDescription、Visibility、Archived状態の差異は警告として報告します。Destinationの管理設定やImport仕様によりVisibilityがPrivateへ変わることがあるため、受入確認で継続可否を判断してください。

`failed_relations`が1件以上あれば、Import Statusが`finished`でも移行失敗として扱います。

## GitLab標準Exportへ委ね、手動確認する項目

次の項目はGitLab標準のExport Archiveへ含まれる可能性がありますが、GitLab Version、Edition、機能構成によって結果が変わります。本ツールは完全性を自動照合しないため、移行されたものとして決めつけず、Pilotと本番受入で確認してください。

- Git Repository、Branch、Tag、Commit履歴
- Issue、Merge Request、Comment、作成者、Approval
- Wiki、Board、Badge、Epic、Iteration
- Members、継承権限、Group共有、招待
- Protected Branch / Tag
- LFSと大容量Repository
- Visibilityなど、自動照合で警告となる属性

Group配下へImportする場合、Issue、Merge Request、Comment等の作成者を正しく対応させるには、移行前に[ユーザーマッピング](user-mapping.md)を完了する必要があります。個人NamespaceへのImportでは、このマッピング自体がサポートされません。

## 移行対象外として別途再設定する項目

次の項目は、本ツールによる移行・復元を前提にしません。事前に棚卸しし、担当者と再設定手順を決めてください。

- GitLabユーザーアカウントの作成
- CI/CD VariableとSecret
- WebhookとWebhook Secret
- Personal / Group / Project Access Token
- Deploy Token
- RunnerとRunner Token
- Pipeline Schedule
- Push Rule
- SAML / LDAP連携
- Container Registry Image
- Package Registry
- Job Artifact
- 外部サービスとの接続情報、認証情報

秘密情報はExportで安全に復元されると想定せず、Secrets Manager等の正規データから再発行・再設定してください。

## ツールが行わない操作

- 同名Group / Projectの自動統合
- Destinationの既存Group / Projectの上書き
- SourceまたはDestinationの自動削除
- 途中停止後の自動Resume
- DNS、案内、権限切替などのCutover
- Backup、Restore、変更凍結、切り戻し

途中で失敗した場合は同じ操作を無条件で再実行せず、Manifestと作成済みDestinationリソースを保全して移行責任者へ連絡してください。

## Version互換性

[GitLab公式のファイルImport互換範囲](https://docs.gitlab.com/user/project/settings/import_export/#compatibility)は、移行先から2 Minor Version以内です。

開発時にはGitLab 15.3.3 EEをSource、GitLab 19.1.1 EEをDestinationとした移行を確認しましたが、この組み合わせは公式互換範囲外です。実機確認はGitLabの互換保証を置き換えません。実際のEdition、Patch Version、機能構成、データ量を使ったPilotと、移行責任者による例外承認が必要です。

実際にExportされる項目はGitLab Versionによって変わります。SourceとDestinationそれぞれのGitLab Source Codeにある`project/import_export.yml`と`group/import_export.yml`を確認し、対象機能が含まれるかをPilot前に判断してください。

## 完了条件

次をすべて満たした時点で移行完了とします。

1. Manifestの自動照合に失敗がない。
2. `failed_relations`が0件である。
3. [受入確認チェックリスト](acceptance-checklist.md)の手動項目を確認した。
4. 対象外項目の再設定を完了した。
5. Group Owner、GitLab管理者、移行責任者が結果を承認した。
