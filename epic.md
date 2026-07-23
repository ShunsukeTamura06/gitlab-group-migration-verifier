# GitLabグループ移行検証 追加仕様書

本仕様は、既存の「GitLab 15.3.3 → 19.1.1 Project Export / Import移行検証仕様書」に追加する。

プロジェクト単体だけでなく、グループ階層およびグループレベルのデータを含めて、GitLab 15.3.3からGitLab 19.1.1へ直接移行できるかを検証する。

---

# 1. 検証対象の拡張

既存の検証対象に、以下を追加する。

1. GitLab 15.3.3でグループをエクスポートできるか
2. エクスポートしたグループをGitLab 19.1.1へ直接インポートできるか
3. トップレベルグループを移行できるか
4. サブグループを含む階層構造を維持できるか
5. グループ名、パス、説明、表示レベルなどがどのように変化するか
6. グループメンバーと権限が維持されるか
7. グループラベル、マイルストーン、ボード、バッジなどが維持されるか
8. GitLab EE固有のEpic、Iteration、Group Wikiなどが維持されるか
9. グループ配下のプロジェクトを正しいNamespaceへ移行できるか
10. グループEpicとプロジェクトIssueなどの関連性が維持されるか
11. グループExportに含まれない項目を特定できるか
12. グループ移行とプロジェクト移行を一連の処理として自動化できるか
13. 階層の途中で失敗した場合に安全に再実行できるか
14. 移行元と移行先のグループ構造を自動比較できるか

---

# 2. 重要な前提

## 2.1 グループとプロジェクトは別々に移行する

グループのファイルExportには、グループ配下のプロジェクト本体は含まれない。

したがって、移行処理は以下の順序で実行する。

```text
1. 移行先ユーザーを準備
2. トップレベルグループをExport
3. トップレベルグループをImport
4. サブグループ階層を検証
5. 各プロジェクトを個別にExport
6. 移行後の対応するグループ／サブグループへImport
7. グループとプロジェクト間の関連性を検証
8. グループ・プロジェクト全体のレポートを生成
```

グループレベルの関連性を保持するため、必ずグループを先に移行し、その後にプロジェクトを移行する。

## 2.2 互換性保証外である

GitLabの公式仕様では、グループのファイルExportも移行先から最大2マイナーバージョン前までが互換範囲である。

今回の15.3.3から19.1.1への直接Importは公式互換範囲外であるため、本検証では実際の成功可否とデータ欠落を実証する。

## 2.3 グループのファイルExport方式は非推奨扱いである

グループのファイルExport／Import方式はGitLab 14.6で非推奨になっており、一般にはDirect Transferが推奨されている。

ただし、本検証では以下の理由により、ファイルExport／Importを明示的に検証する。

* GitLab 15.3.3と19.1.1の直接移行可能性を確認するため
* 閉域環境やオフライン環境でも利用可能な方式を確認するため
* プロジェクトのExport／Import方式と統一した移行プログラムを検討するため
* 社内環境でDirect Transferが利用できない場合の代替手段を確認するため

ファイル方式が成功しても、それだけでGitLab公式の推奨方式になったとは判断しない。

---

# 3. テスト用グループ構成

移行元GitLab 15.3.3に、以下の構造を自動作成する。

```text
migration-source
├── platform
│   ├── backend
│   │   ├── api-service
│   │   └── batch-service
│   └── frontend
│       └── web-application
├── data
│   ├── analytics
│   │   └── analytics-engine
│   └── data-pipeline
├── 日本語グループ
│   └── 日本語プロジェクト
├── empty-subgroup
└── root-project
```

検証対象には以下を含める。

* トップレベルグループ
* 1階層のサブグループ
* 2階層以上のサブグループ
* 空のサブグループ
* プロジェクトを直接持つトップレベルグループ
* プロジェクトを持つサブグループ
* 日本語名を含むグループ
* 日本語説明を含むグループ
* 同じ名前を別階層で使用するグループ
* Private、Internal、Publicの各表示レベル
* 可能な範囲で異なる権限設定を持つグループ

GitLabの設定上、InternalまたはPublicが禁止されている場合は、その事実を記録して対象外とする。

---

# 4. グループテストデータ

トップレベルグループおよびサブグループへ、APIを使って以下のデータを作成する。

## 4.1 共通項目

* グループ名
* グループパス
* グループ説明
* 表示レベル
* Avatar
* グループメンバー
* Owner
* Maintainer
* Developer
* Reporter
* Guest
* グループラベル
* グループマイルストーン
* グループボード
* グループバッジ
* サブグループ
* グループ変数
* グループWebhook
* Deploy Token
* Runner関連設定
* Push Rule
* 可能ならGroup Wiki

Group CI/CD Variable、Webhook、Deploy Tokenなどは、移行されることを前提にしない。

「移行されないことを確認するためのテストデータ」として作成する。

## 4.2 Enterprise Edition機能

GitLab EEのライセンスまたは試用状態で利用可能な場合、以下も作成する。

* Epic
* Epicコメント
* Epic Label
* Epicと子Epicの階層
* EpicとプロジェクトIssueの関連付け
* Iteration
* Iteration Cadence
* Group Wiki
* Epic Board

ライセンス上利用できない項目は、失敗ではなく以下として記録する。

```text
not_available_due_to_license
```

## 4.3 文字列の境界条件

以下を含むグループデータを作成する。

* 日本語
* 絵文字
* Markdown
* 長い説明
* 改行
* 特殊文字を含むラベル
* 同名のマイルストーン
* 同名のラベル
* Unicodeを含むWiki本文
* 添付ファイルへの参照

---

# 5. グループExport／Import API

## 5.1 グループExport

移行元GitLabに対して以下を使用する。

```text
POST /api/v4/groups/:id/export
```

Export開始成功時には、通常202 Accepted相当のレスポンスが返る。

## 5.2 グループExportファイルの取得

以下を使用する。

```text
GET /api/v4/groups/:id/export/download
```

グループExportには、プロジェクトExportのような明示的なStatus取得APIが存在しない可能性がある。

そのため、以下の方式で完了を待つ。

```text
POST /groups/:id/export
    ↓
一定間隔でGET /groups/:id/export/download
    ↓
404なら生成中として待機
    ↓
200かつ有効なtar.gzなら完了
```

公式APIでは、Exportファイルが利用可能になるまでは、ダウンロードAPIが404を返す。

ただし、以下の404を区別する。

* Export生成中
* Group IDが存在しない
* 権限がないことによる秘匿404
* Export機能が無効
* API仕様差
* Exportデータが削除済み

最大待機時間を設定し、無限にポーリングしない。

## 5.3 グループImport

移行先GitLabに対して以下を使用する。

```text
POST /api/v4/groups/import
```

送信項目：

```text
file
name
path
parent_id
```

`parent_id`は、既存グループ配下へImportする場合に使用する。

Import APIのレスポンスはGitLabバージョンにより異なる可能性があるため、以下の両方に対応する。

1. レスポンスからImport後のGroup IDまたはFull Pathを取得できる場合
2. レスポンスにGroup IDがないため、指定したFull PathをGroups APIで検索する場合

Import後は、次のAPIでGroupの出現を確認する。

```text
GET /api/v4/groups/:id
GET /api/v4/groups/:url_encoded_full_path
```

Import直後にGroupが存在しても、関連データの作成が完了していない可能性を考慮する。

グループ内のラベル、マイルストーン、メンバー、サブグループなどが一定期間変化しなくなるまでポーリングするか、GitLabログとSidekiq状態を確認する。

---

# 6. 移行プログラムの追加構成

以下のファイルを追加する。

```text
src/gitlab_migrator/
├── group_exporter.py
├── group_importer.py
├── group_migrator.py
├── group_verifier.py
├── namespace_mapper.py
└── hierarchy.py
```

各モジュールの責務は以下とする。

## group_exporter.py

* Group Export開始
* Download APIのポーリング
* 404判定
* Exportアーカイブの保存
* ファイルサイズ計算
* SHA-256計算
* Export結果の記録

## group_importer.py

* 移行先Parent Groupの確認
* Group Import実行
* Import後Groupの特定
* Group階層の確認
* Import結果の記録

## group_migrator.py

* グループ単位の移行フロー制御
* グループを先に移行
* 配下プロジェクトを後から移行
* Namespaceの対応関係管理
* 再実行制御

## group_verifier.py

* 移行元と移行先のGroup比較
* サブグループ階層比較
* グループレベルデータ比較
* グループとプロジェクト間の関連性比較
* 差分レポート生成

## namespace_mapper.py

以下の対応関係を管理する。

```text
source_group_id
source_full_path
destination_group_id
destination_full_path
source_parent_id
destination_parent_id
```

## hierarchy.py

* グループツリーの取得
* 親子関係の解決
* 深さ優先または幅優先での移行順序決定
* 循環や不正な階層情報の検出
* 移行対象Groupの重複排除

---

# 7. CLIの追加

以下のCLIを実装する。

## グループ一覧

```bash
python -m gitlab_migrator.cli list-groups
```

## グループExport

```bash
python -m gitlab_migrator.cli export-group \
  --source-group-id 10
```

## グループImport

```bash
python -m gitlab_migrator.cli import-group \
  --archive work/exports/groups/10-migration-source.tar.gz \
  --destination-name migration-destination \
  --destination-path migration-destination
```

既存のParent Group配下へImportする場合：

```bash
python -m gitlab_migrator.cli import-group \
  --archive work/exports/groups/10-migration-source.tar.gz \
  --destination-name migration-destination \
  --destination-path migration-destination \
  --destination-parent-id 20
```

## グループツリー全体の移行

```bash
python -m gitlab_migrator.cli migrate-group \
  --source-group-id 10 \
  --destination-path migration-destination \
  --include-projects
```

## グループだけ移行

```bash
python -m gitlab_migrator.cli migrate-group \
  --source-group-id 10 \
  --destination-path migration-destination \
  --exclude-projects
```

## グループ検証

```bash
python -m gitlab_migrator.cli verify-group \
  --source-group-id 10 \
  --destination-group-id 20
```

## グループとプロジェクトを含む全体検証

```bash
python -m gitlab_migrator.cli verify-tree \
  --source-group-id 10 \
  --destination-group-id 20
```

## レポート生成

```bash
python -m gitlab_migrator.cli report \
  --source-group-id 10
```

---

# 8. グループ移行フロー

`migrate-group --include-projects`は、以下の処理を実行する。

```text
1. 移行元グループ情報を取得
2. 配下の全サブグループを列挙
3. 配下の全プロジェクトを列挙
4. グループ・プロジェクト構造をManifestへ保存
5. 移行元グループをExport
6. Export完了までDownload APIをポーリング
7. Exportアーカイブを保存
8. 移行先へGroup Import
9. 移行後のトップレベルグループを特定
10. 全サブグループの対応関係を解決
11. Group構造を検証
12. 各プロジェクトの移行先Namespaceを決定
13. プロジェクトを1件ずつExport／Import
14. プロジェクト移行結果を検証
15. GroupとProject間の関連性を検証
16. 全体レポートを生成
```

グループExportにサブグループが含まれている場合は、同じサブグループを個別に再Importして重複させてはならない。

最初にトップレベルグループのExportファイルだけで、サブグループがどこまで作成されるかを確認する。

不足しているサブグループだけを個別移行する設計にはせず、まず実際の挙動を記録する。

---

# 9. グループManifest

グループ単位のManifestをJSONで保存する。

```json
{
  "source": {
    "gitlab_version": "15.3.3",
    "group_id": 10,
    "name": "migration-source",
    "path": "migration-source",
    "full_path": "migration-source",
    "parent_id": null,
    "visibility": "private"
  },
  "destination": {
    "gitlab_version": "19.1.1",
    "group_id": 20,
    "name": "migration-destination",
    "path": "migration-destination",
    "full_path": "migration-destination",
    "parent_id": null,
    "visibility": "private"
  },
  "export": {
    "status": "finished",
    "archive_path": "work/exports/groups/10-migration-source.tar.gz",
    "archive_size": 123456,
    "sha256": "..."
  },
  "import": {
    "status": "finished",
    "response": {},
    "resolved_by": "full_path"
  },
  "hierarchy": {
    "source_group_count": 7,
    "destination_group_count": 7,
    "matched_group_count": 7,
    "missing_groups": [],
    "extra_groups": []
  },
  "verification": {
    "status": "warning",
    "name_match": true,
    "path_match": true,
    "hierarchy_match": true,
    "members_match": true,
    "labels_match": true,
    "milestones_match": true,
    "boards_match": true,
    "badges_match": true,
    "wikis_match": true,
    "epics_match": true,
    "group_variables_match": false,
    "webhooks_match": false
  },
  "projects": [
    {
      "source_project_id": 100,
      "source_path": "migration-source/platform/backend/api-service",
      "destination_project_id": 200,
      "destination_path": "migration-destination/platform/backend/api-service",
      "migration_status": "finished",
      "verification_status": "success"
    }
  ],
  "timestamps": {
    "started_at": "...",
    "finished_at": "..."
  }
}
```

APIレスポンス全文を保存する場合は、秘密情報をマスキングする。

---

# 10. グループ比較方法

## 10.1 グループ階層

移行元と移行先について、以下の形式で正規化したツリーを作成する。

```json
[
  {
    "relative_path": ".",
    "name": "migration-source"
  },
  {
    "relative_path": "platform",
    "name": "platform"
  },
  {
    "relative_path": "platform/backend",
    "name": "backend"
  },
  {
    "relative_path": "platform/frontend",
    "name": "frontend"
  }
]
```

トップレベルグループのパスは移行時に変更できるため、絶対的な`full_path`ではなく、トップレベルからの相対パスで比較する。

比較対象：

* サブグループ数
* 階層の深さ
* 親子関係
* 相対パス
* Group名
* Group説明
* 表示レベル
* 空のサブグループ
* 各グループに所属するプロジェクト

## 10.2 メンバー

IDは一致を要求しない。

以下を論理キーとして比較する。

```text
username
public_email
access_level
membership_type
```

以下を区別する。

* Direct Member
* Inherited Member
* Invited Member
* Group ShareによるMember

移行前後で権限が変化した場合は、以下を記録する。

```text
source_access_level
destination_access_level
source_membership_type
destination_membership_type
```

移行前に移行先ユーザーが存在しない場合と、存在する場合の両方をテストする。

## 10.3 グループラベル

比較対象：

* name
* description
* color
* text_color
* priority

ラベルのPriorityが維持されない場合は、仕様上の制約として記録する。

## 10.4 グループマイルストーン

比較対象：

* title
* description
* state
* start_date
* due_date

IDは比較しない。

同名マイルストーンが移行先に存在する場合の動作も、異常系として確認する。

## 10.5 グループボード

比較対象：

* Board名
* Board数
* Board List
* ListのLabel
* Listの順序

APIで取得できない項目は、Rails APIまたは画面の手動確認に切り替えるのではなく、取得不能としてレポートする。

## 10.6 グループバッジ

比較対象：

* name
* link_url
* image_url
* rendered_link_url
* rendered_image_url

ホスト名部分が移行元と移行先で異なる場合は、正規化して比較する。

## 10.7 Group Wiki

比較対象：

* ページ数
* title
* slug
* content
* format
* 添付ファイル参照

利用ライセンスにより作成できない場合は対象外とする。

## 10.8 Epic

利用可能な場合、以下を比較する。

* IID
* title
* description
* state
* labels
* milestone
* author
* assignee
* parent Epic
* child Epic
* Project Issueとの関連
* コメント

特に以下を重点確認する。

```text
グループを先にImport
    ↓
プロジェクトを対応するGroupへImport
    ↓
EpicとProject Issueの関連が復元されるか
```

## 10.9 Iteration

利用可能な場合、以下を比較する。

* title
* description
* start_date
* due_date
* state
* cadence
* Issueとの関連

## 10.10 グループ設定

以下を比較可能な範囲で確認する。

* visibility
* project_creation_level
* subgroup_creation_level
* default_branch_protection
* request_access_enabled
* lfs_enabled
* emails_disabled
* mentions_disabled
* shared_runners_setting
* membership_lock
* two_factor_grace_period
* require_two_factor_authentication

GitLab 15.3.3と19.1.1で設定項目が追加・廃止・改名されている可能性があるため、以下に分類する。

```text
same
changed
not_available_on_source
not_available_on_destination
not_exported
not_comparable
```

---

# 11. 移行対象外項目の確認

グループファイルExportで、少なくとも以下は移行されない可能性が高いため、個別に確認する。

* プロジェクト本体
* Group CI/CD Variable
* Group Webhook
* Deploy Token
* Runner Token
* SAML Discovery Token
* Upload
* Group Push Rule
* Pending Invitation
* その他の暗号化されたToken

現行GitLab公式資料では、グループファイルExportにプロジェクト、Runner Token、SAML Discovery Token、Uploadは含まれないとされている。

結果は以下のように分類する。

```text
migrated
migrated_with_changes
not_migrated_as_documented
not_migrated_due_to_version_difference
not_available_due_to_license
unknown
```

「移行されなかった」という結果だけでは失敗にしない。

Export対象外であることが公式仕様または実装上確認できる場合は、補完移行が必要な項目として記録する。

---

# 12. プロジェクトとの統合検証

グループ移行後、既存のProject Export／Importプログラムを使用して、各プロジェクトを対応する移行先GroupへImportする。

## 12.1 Namespaceマッピング

例：

```text
移行元:
migration-source/platform/backend/api-service

移行先:
migration-destination/platform/backend/api-service
```

以下のマッピングを生成する。

```json
{
  "migration-source": "migration-destination",
  "migration-source/platform": "migration-destination/platform",
  "migration-source/platform/backend": "migration-destination/platform/backend"
}
```

プロジェクトの移行先Namespaceは、このマッピングから決定する。

## 12.2 プロジェクト配置

以下を確認する。

* 全プロジェクトが正しいGroupへ配置される
* トップレベルGroup直下のProjectが維持される
* サブグループ配下のProjectが維持される
* 同名Projectが別Groupに存在しても混同しない
* 空のGroupが消失しない
* Project Pathが変化しない
* Project Full Pathのルート部分だけが意図どおり変更される

## 12.3 グループとプロジェクトの関連

利用可能な場合、以下を確認する。

* Group EpicとProject Issue
* Group MilestoneとProject Issue
* Group LabelとProject Issue
* IterationとProject Issue
* Group MemberのProjectへの継承
* Default Branch Protectionの継承
* Group Runnerの利用状態
* Group Access Tokenに依存する設定

---

# 13. 再実行性

グループ移行でも、以下の状態を管理する。

```text
not_started
group_export_started
group_export_finished
group_archive_downloaded
group_import_started
group_import_finished
group_verification_finished
projects_migration_started
projects_migration_finished
tree_verification_finished
failed
```

移行先にGroupが存在する場合、プログラムは自動削除や上書きをしてはならない。

以下の動作を選択できるようにする。

```text
デフォルト:
既存Groupを検出して停止

--resume:
Manifestに記録されたGroup IDと一致する場合だけ続行

--reuse-existing-group:
既存Groupを明示的に利用

--destination-path:
異なるPathへImport

--force:
テスト環境のみで許可
```

`--force`でも既存Groupを自動削除してはならない。

削除が必要な場合は、別の明示的なテスト用コマンドに分離する。

---

# 14. Makefileの追加

以下を追加する。

```bash
make bootstrap-groups
```

テスト用のグループ階層とグループレベルデータを作成する。

```bash
make migrate-groups
```

グループ階層だけを移行する。

```bash
make verify-groups
```

グループ階層とグループレベルデータを比較する。

```bash
make migrate-tree
```

グループを先に移行し、その後に全プロジェクトを移行する。

```bash
make verify-tree
```

グループ、サブグループ、プロジェクトおよび相互関連を検証する。

```bash
make report-tree
```

グループとプロジェクトを統合したレポートを生成する。

既存の`make all`は以下の順序へ変更する。

```text
1. make up
2. make wait
3. make bootstrap
4. make bootstrap-groups
5. make migrate-groups
6. make verify-groups
7. make migrate
8. make verify
9. make verify-tree
10. make report-tree
```

---

# 15. Integration Testの追加

以下のIntegration Testを実装する。

## 15.1 トップレベルグループ

* Export開始が成功する
* Exportファイルをダウンロードできる
* 19.1.1へImportできる
* Import後GroupをAPIで取得できる

## 15.2 サブグループ

* 1階層のSubgroupが作成される
* 2階層以上のSubgroupが作成される
* 親子関係が一致する
* 空のSubgroupが維持される
* 日本語名のSubgroupが維持される

## 15.3 メンバー

* 移行先に同一ユーザーが存在する場合
* 移行先にユーザーが存在しない場合
* Owner
* Maintainer
* Developer
* Reporter
* Guest
* Inherited Member

## 15.4 グループデータ

* Label
* Milestone
* Board
* Badge
* Wiki
* Epic
* Iteration

## 15.5 プロジェクト連携

* Group Import後にProject Importを実行
* 正しいNamespaceへ配置される
* Group EpicとProject Issueの関連性
* Group MilestoneとProject Issueの関連性
* Member権限の継承

## 15.6 異常系

* 不正Group ID
* Group Owner権限がないToken
* Export完了前のDownload
* Exportタイムアウト
* 不正なGroup Exportファイル
* 移行先に同名Groupが存在する
* 移行先Parent Groupが存在しない
* Importファイルサイズ超過
* Group Import後、Project Importの途中で停止
* 途中停止後の`--resume`
* Import先の表示レベル制限
* 移行先ユーザー不足
* 同名マイルストーンの競合

---

# 16. グループ移行レポート

レポートに以下の表を追加する。

## 16.1 グループ別結果

| 相対パス             | Export | Import | 階層 | Members | Labels | Milestones | 総合 |
| ---------------- | -----: | -----: | -: | ------: | -----: | ---------: | -: |
| .                |     成功 |     成功 | 一致 |      一致 |     一致 |         一致 | 成功 |
| platform         |     含有 |     成功 | 一致 |      一致 |     一致 |         一致 | 成功 |
| platform/backend |     含有 |     成功 | 一致 |      警告 |     一致 |         一致 | 警告 |
| empty-subgroup   |     含有 |     成功 | 一致 |      一致 |   該当なし |       該当なし | 成功 |

サブグループがトップレベルGroupのExportファイルに含まれていた場合、Export列には`含有`と表示する。

## 16.2 機能別結果

| 項目                  | 結果   | 分類                         | 詳細             |
| ------------------- | ---- | -------------------------- | -------------- |
| Group hierarchy     | 一致   | migrated                   | 全7グループ一致       |
| Members             | 一部差異 | migrated_with_changes      | Ownerが変更       |
| Labels              | 一致   | migrated                   | 色・説明一致         |
| Label priority      | 欠落   | not_migrated_as_documented | 再設定が必要         |
| Group variables     | 欠落   | not_migrated_as_documented | API補完が必要       |
| Webhooks            | 欠落   | not_migrated_as_documented | API補完が必要       |
| Projects            | 個別移行 | not_in_group_export        | Project APIで移行 |
| Epic-Issue relation | 一致   | migrated                   | 関連復元を確認        |

## 16.3 グループ階層差分

```text
Missing groups:
- platform/frontend

Extra groups:
- imported-temp-group

Changed groups:
- data: visibility internal → private
```

## 16.4 プロジェクト配置差分

```text
Wrong namespace:
- api-service
  expected: migration-destination/platform/backend/api-service
  actual: migration-destination/api-service
```

---

# 17. グループ移行の合否基準

## 17.1 必須成功条件

以下をすべて満たした場合、グループの直接Export／Importは「技術的に成立」と判定する。

* GitLab 15.3.3でGroup Exportを開始できる
* Group Exportファイルを取得できる
* GitLab 19.1.1でGroup Importを実行できる
* Import後のトップレベルGroupへアクセスできる
* サブグループ階層が再現される
* 各Groupの相対パスが一致する
* 空のサブグループが維持される
* グループ配下のProjectを正しいNamespaceへImportできる
* グループ移行後にプロジェクト移行を自動実行できる
* 移行されなかった項目を自動検出できる
* 既存Groupを破壊せず再実行できる
* グループとプロジェクトの統合レポートを生成できる

## 17.2 警告扱い

以下は発生しても、直ちに全体失敗とはしない。

* VisibilityがPrivateへ変更される
* メンバーの一部がImport実行者へ置き換わる
* Owner権限が変化する
* Group Variableが移行されない
* Group Webhookが移行されない
* Deploy Tokenが移行されない
* Runner設定が移行されない
* Label Priorityが移行されない
* Group Push Ruleが移行されない
* ライセンス上利用できないEE機能がある
* 日時や内部IDが変化する

## 17.3 失敗扱い

以下は重大な失敗とする。

* Group Import自体が失敗する
* トップレベルGroupが作成されない
* サブグループが大量に欠落する
* 親子関係が崩れる
* プロジェクトを正しいNamespaceへ配置できない
* Group Exportが完了してもファイルを取得できない
* Importが成功扱いなのにGroupが利用不能
* グループ階層の差分を検出できない
* 再実行によって既存GroupまたはProjectを破壊する

---

# 18. 最終判定形式

最終回答には、プロジェクト結果に加えて以下を記載する。

```text
グループ直接Export / Import：
成功 / 部分成功 / 失敗

トップレベルグループ：
一致 / 差異あり

サブグループ階層：
完全一致 / 一部欠落 / 大幅欠落

グループメンバー：
完全一致 / 一部変更 / 大幅欠落

グループラベル：
完全一致 / 一部変更 / 大幅欠落

グループマイルストーン：
完全一致 / 一部変更 / 大幅欠落

グループボード：
完全一致 / 一部変更 / 大幅欠落

Group Wiki：
完全一致 / 一部変更 / 対象外 / 大幅欠落

Epic：
完全一致 / 一部変更 / 対象外 / 大幅欠落

EpicとProject Issueの関連：
維持 / 一部欠落 / 対象外 / 消失

プロジェクトのNamespace配置：
完全一致 / 一部誤配置 / 大幅誤配置

補完移行が必要な項目：
項目一覧

本番採用判断：
採用候補 / 補完処理が必要 / 非推奨
```

各判定には、APIレスポンス、Exportファイル、Manifest、GitLabログ、比較結果などの根拠を添える。

---

# 19. Codexへの追加指示

Codexは、プロジェクト移行の実装に進む前に、以下を最小構成で確認すること。

```text
1. 15.3.3にトップレベルGroupとSubgroupを作成
2. Group LabelとGroup Milestoneを作成
3. Group Export APIを実行
4. Download APIを404から200になるまでポーリング
5. Exportファイルを保存
6. 19.1.1へGroup Import
7. Import後のGroup IDとFull Pathを特定
8. Subgroup、Label、Milestoneを比較
9. Group配下へ1つのProjectをImport
10. Namespaceと関連性を確認
```

この最小検証に失敗した場合は、大規模な移行プログラムを先に実装しない。

失敗時には以下を確認する。

* Group Export APIレスポンス
* Group Import APIレスポンス
* Railsログ
* Sidekiqログ
* Exportアーカイブの構造
* Group Import Exportの内部Format Version
* 15.3.3と19.1.1の`group/import_export.yml`
* 移行元と移行先のライセンス差
* Import Source設定
* 最大Importファイルサイズ
* Visibility制限
* ユーザーマッピング条件

最終的には、以下を1コマンドで実行可能にする。

```bash
make migrate-tree
```

このコマンドにより、グループ階層のExport／Import、配下プロジェクトのExport／Import、全体検証、レポート生成までを実行すること。
