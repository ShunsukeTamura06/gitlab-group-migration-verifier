# GitLab 15.3.3 → 19.1.1 最小移行検証結果

検証日: 2026-07-23

> [!NOTE]
> この最小検証後、8 Group・7 Projectの一括移行検証を完了した。後続結果は[全Project一括移行検証結果](full-project-validation-2026-07-23.md)を参照。

## 結論

```text
グループ直接Export / Import：成功
トップレベルグループ：意図した名称変更以外は一致
サブグループ階層：完全一致（2 / 2）
グループラベル：完全一致
グループマイルストーン：完全一致
プロジェクトのNamespace配置：完全一致
補完移行が必要な項目：最小検証では未判定
本番採用判断：補完処理と全量検証が必要
```

公式互換範囲外の15.3.3から19.1.1へ、Group file Export / Importを直接実行できた。最小データではSubgroup、Label、Milestoneが最終的に一致し、個別Projectも対応Subgroupへ配置できた。ただし、これは最小構成の技術的成立を示すものであり、全機能・全量データの本番採用判断ではない。

## 実行環境

| 項目 | 値 |
|---|---|
| Source | GitLab EE 15.3.3 (`gitlab/gitlab-ee:15.3.3-ee.0`) |
| Destination | GitLab EE 19.1.1 (`gitlab/gitlab-ee:19.1.1-ee.0`) |
| Docker | 4 CPU / 約3.8GiB |
| 実行方式 | SourceとDestinationの逐次起動 |

2台同時起動ではDocker APIが無応答になった。実測メモリはSource単体が約2.0GiB、Destination単体が約2.9GiBだったため、SourceでExportとSnapshot取得後に停止し、Destinationを起動してImportする方式へ切り替えた。Named Volumeは保持した。

## Group Export

| 項目 | 結果 |
|---|---|
| Source Group | ID 4 `migration-source` |
| Source Subgroup | ID 5 `migration-source/subgroup` |
| Export API | 成功 |
| Download API | 404ポーリング後に成功 |
| Archive | `work/exports/groups/4-migration-source.tar.gz` |
| Size | 1,833 bytes |
| SHA-256 | `0e4cab39f93a10b48c2402c1e48243bd38c3cc33f0d7de6159787b48d839e249` |

5秒間隔のDownloadポーリングではHTTP 429が発生した。実装を修正し、429を一時状態として扱い`Retry-After`を尊重したうえで、20秒間隔の再実行に成功した。

アーカイブにはGroup 4/5のJSONと、各Groupのmembers、labels、milestones、boards、badges、epics、namespace settingsのNDJSONが含まれていた。Project本体は含まれていなかった。

## Group Importと比較

| 項目 | 結果 |
|---|---|
| Import API | `202 Accepted` |
| Destination Group | ID 34 `migration-destination` |
| Destination Subgroup | ID 35 `migration-destination/subgroup` |
| Group ID解決 | ImportレスポンスにIDなし、Full Pathで解決 |
| Group数 | Source 2 / Destination 2 / 一致2 |
| Missing / Extra | なし / なし |
| Label | 一致 |
| Milestone | 一致 |

Import直後の初回比較ではSubgroupの説明が空だったが、後続の非同期処理完了後に元の説明へ更新され、再比較で完全一致した。このため、Group作成の確認だけでImport完了と判定せず、階層とGroupデータが一定期間安定するまで待つ必要がある。

比較根拠:

- `work/manifests/source-group-4-snapshot.json`
- `work/manifests/group-4-to-34-verification.json`

## Project ImportとNamespace

| 項目 | 結果 |
|---|---|
| Source Project | ID 2 `migration-source/subgroup/api-service` |
| Project Archive | `work/exports/projects/2-api-service.tar.gz` |
| Size | 5,526 bytes |
| SHA-256 | `87de38fbad4ce8a233b7ea1e95b5e365affd2b84d5802e8df0886881060abbbd` |
| Destination Project | ID 1 `migration-destination/subgroup/api-service` |
| Import status | `finished` |
| Import error | なし |
| Default branch | `main` |
| Repository | 非空 |
| Namespace | 完全一致 |

Destinationの`import_sources`初期値は空配列で、Project Import APIはHTTP 403を返した。Application Settingsで`gitlab_project`を有効化後、Importは受理された。受付直後は`import_status: scheduled`だったため、Projectの存在だけで成功とせず、`finished`までポーリングした。

## 実装へ反映した知見

- Group Download APIの404と429を一時状態として扱う。
- Group ImportレスポンスにIDがない場合はFull Pathで解決する。
- Import直後のGroupデータは非同期更新されるため安定化待機を行う。
- Project Import Source設定を事前確認する。
- Projectは`import_status=finished`まで待つ。
- 既存Group / Projectを自動削除・上書きしない。
- 4GB Docker環境ではSource / Destinationを逐次起動する。

## 未検証

Membersの各Access Level、Board、Badge、Wiki、Epic、Iteration、Variable、Webhook、Deploy Token、Runner、Push Rule、招待、同名競合、途中停止後のresume、および仕様3章の全Groupツリーは未検証。これらは最小検証の成功を前提に次Phaseで実施する。
