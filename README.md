# overload-party-newsfeed

クラウドニュース収集 Cloud Run Job。AWS / Azure / Google Cloud / Oracle Cloud の公式 RSS を定期取得し、`news-article-collected` Pub/Sub トピックへ publish する。DB / GCS / Vertex AI への副作用は持たない。

詳細は [サービス設計書](docs/ARCHITECTURE.md) を参照。

## サービス間連携

```
Cloud Scheduler (2 時間おき)
  └─ Newsfeed (Cloud Run Job)
       ├─ RSS (AWS / Azure / Google Cloud / OCI)
       └─ Pub/Sub publish
            └─ news-article-collected → News (overload-party-news)
```

- REST エンドポイントなし（バッチジョブ）
- 記事の永続化・要約生成・配信は News サービスの責務 (ADR-019)

## 環境変数

| 変数名 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | はい | --- | Pub/Sub publisher の対象プロジェクト |
| `PUBSUB_EMULATOR_HOST` | いいえ | --- | ローカル / テスト用の Pub/Sub emulator ホスト |

必須変数が未設定なら起動時に即 fail する。トピック名は `news-article-collected` に固定（契約定数として実装側でハードコード）。

## 公開パッケージ

[packages/newsfeed-constants-npm/](packages/newsfeed-constants-npm/) に `CloudNewsSource` の TypeScript 型を npm パッケージとして公開している。Gateway の TS 型定義経由で client が cloud news source 値を型付けするために使う。

SSoT: `data/newsfeed_constants.yaml` → `python3 scripts/generate_types.py` で再生成。
