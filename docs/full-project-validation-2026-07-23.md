# GitLab 15.3.3 → 19.1.1 全Project一括移行検証結果

検証日: 2026-07-23

## 結論

```text
Group一括Export / Import：成功
Group階層：8 / 8一致、Missing 0、Extra 0
全Project一括Export / Import：7 / 7成功
Project Namespace：7 / 7一致、Missing 0、Extra 0
Project Path / Name：完全一致
Default Branch：7 / 7でmain
Repository：7 / 7で非空
警告：Public / Internal VisibilityがPrivateへ変更
```

4GB級のDocker環境では2台を同時起動できないため、Source側で`export-tree`、Destination側で`import-tree`を実行する二段階方式で検証した。両コマンドは`migrate-tree`と同じExporter、Importer、Verifierを使用する。

## テストツリー

```text
migration-full-source
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
├── japanese-group
│   └── japanese-project（表示名: 日本語プロジェクト）
├── empty-subgroup
└── root-project
```

Groupはルートを含めて8件、Projectは7件。ルート直下、1階層、2階層、日本語、空Group、Private / Internal / Publicを含めた。

## Export

| 対象 | Size | SHA-256 |
|---|---:|---|
| Group tree | 2,659 bytes | `2dc69b9d46bbbfc4efd9d5b2416eec22482b17e8bcbf09c83ffa324d44bc90fd` |
| analytics-engine | 5,492 bytes | `f57e281c9616bf4353647c2f61f3ee35f1a0459d62c993a8082d51d31ccf22b5` |
| data-pipeline | 5,468 bytes | `2989e5786fa7e8268737b135196f793da08f76866eb9beacc6b5cb9ef8ce415c` |
| japanese-project | 5,535 bytes | `b4b1a78d3dc014233548d09d48dbcf7571968e1bbcac1df028455f51f4bf2905` |
| api-service | 5,466 bytes | `e58f3fa501809b2d03e65fe46cfb2735530878c7a87c21f6bf05aa232d7f323c` |
| batch-service | 5,497 bytes | `aeecc9be391fb13807f8a165d732b588496f0b83d4781ba3c5d74733bc31abf7` |
| web-application | 5,487 bytes | `a1508e720c15f6476bb9cf52819f9f730eb283505ff7161190b95acba65000b3` |
| root-project | 5,462 bytes | `0a1a3a704ad998a7ef6370c310ac208715bb52629e300a460ce2e5784a1410e3` |

`export-tree`はProjectごとの完了直後にArchive情報をManifestへ保存した。`import-tree`はImport開始前に全8 Archiveについてtar.gz形式、サイズ、SHA-256を再検証した。

## Importと最終突合

Destination GroupはID 37、`migration-full-destination`として作成された。全7 Projectは次の相対Pathを維持した。

- `data/analytics/analytics-engine`
- `data/data-pipeline`
- `japanese-group/japanese-project`
- `platform/backend/api-service`
- `platform/backend/batch-service`
- `platform/frontend/web-application`
- `root-project`

最終処理では、移行先APIからGroup配下のProject一覧と各Project詳細を再取得した。Source Snapshotと比較し、Project数、相対Path、Name、Path、Description、Archived、Default Branch、Repositoryの空・非空が一致した。

## 警告

SourceでPublicまたはInternalだった一部Group / Projectは、DestinationでPrivateになった。仕様17.2に従い警告扱いとし、Project欠落や誤配置ではないため一括移行自体は成功と判定した。

## 根拠

- Manifest: `work/manifests/full-tree-7.json`
- Group Archive: `work/exports/groups/7-migration-full-source.tar.gz`
- Project Archives: `work/exports/projects/*.tar.gz`

上記実データは機密情報を含み得るためGit管理対象外とし、検証結果とSHA-256だけをこの文書へ記録する。
