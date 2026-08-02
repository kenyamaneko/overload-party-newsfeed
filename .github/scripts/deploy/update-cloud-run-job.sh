#!/usr/bin/env bash
set -euo pipefail

: "${JOB_NAME:?JOB_NAME env required}"
: "${IMAGE:?IMAGE env required}"
: "${IMAGE_TAG:?IMAGE_TAG env required}"
: "${REGION:?REGION env required}"
: "${PROJECT:?PROJECT env required}"

gcloud run jobs update "${JOB_NAME}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --image "${IMAGE}:${IMAGE_TAG}" \
  --quiet
