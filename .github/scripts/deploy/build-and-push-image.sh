#!/usr/bin/env bash
set -euo pipefail

: "${IMAGE:?IMAGE env required}"
: "${IMAGE_TAG:?IMAGE_TAG env required}"

docker build -t "${IMAGE}:${IMAGE_TAG}" -t "${IMAGE}:latest" .
docker push "${IMAGE}:${IMAGE_TAG}"
docker push "${IMAGE}:latest"
