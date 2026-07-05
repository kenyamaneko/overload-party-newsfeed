#!/bin/bash
# newsfeed が publish する Pub/Sub topic を emulator に作成する。
# 実環境では topic は基盤側で作成されるが、newsfeed 単体起動では publish 先が無いと
# 送信が失敗するため、ここで用意する。
# topic 名は compose の env から受け取り、スクリプト内のリテラル管理を避ける。
set -euo pipefail

PROJECT="${PUBSUB_PROJECT_ID:?compose 経由で PUBSUB_PROJECT_ID を設定すること}"
HOST="${PUBSUB_EMULATOR_HOST:?compose 経由で PUBSUB_EMULATOR_HOST を設定すること}"
TOPIC="${NEWS_ARTICLE_COLLECTED_TOPIC:?compose 経由で NEWS_ARTICLE_COLLECTED_TOPIC を設定すること}"

# 既存 (409) は idempotent 再実行として許容し、それ以外の HTTP 失敗は abort する。
put() {
  local url="$1"
  shift
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' -X PUT "$url" "$@")
  case "$code" in
    2*|409) return 0 ;;
    *) echo "PUT $url -> HTTP $code" >&2; return 1 ;;
  esac
}

put "http://${HOST}/v1/projects/${PROJECT}/topics/${TOPIC}"
echo "topic ready: ${TOPIC}"
