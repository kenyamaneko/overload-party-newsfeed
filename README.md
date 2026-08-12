# overload-party-newsfeed

カードゲーム Overload Party のクラウドニュース収集を担う Cloud Run Job。AWS / Azure / Google Cloud の公式 RSS を定期取得し、Vertex AI Gemini で日本語要約・タグ付けして配信する。

## 技術スタック

| レイヤー | 技術 |
|---|---|
| 言語 | Python |
| 実行基盤 | Cloud Scheduler, Cloud Run Job |
| データストア | Upstash Redis |
| AI要約 | Vertex AI Gemini |
| シークレット管理 | Secret Manager |
| 非同期通信 | Cloud Pub/Sub |

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [セットアップ](docs/SETUP.md) | 環境変数・Secret Manager・ローカル開発 |
| [ADR](https://github.com/kenyamaneko/overload-party-common/tree/main/docs/adr)（commonリポジトリ） | 設計判断の背景・理由・結果 |
| [システム構成図](https://github.com/kenyamaneko/overload-party-common#システム構成図)（commonリポジトリ） | Overload Party 全体の構成図 |
| [テスト観点カタログ](https://kenyamaneko.github.io/overload-party-newsfeed/) | テスト名から自動生成した、テスト済みの観点一覧 |
