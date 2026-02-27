#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <owner/repo>"
  exit 1
fi

REPO="$1"

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/${REPO}/branches/main/protection" \
  -f required_status_checks.strict=true \
  -f required_status_checks.contexts[]="test (py3.11)" \
  -f required_status_checks.contexts[]="test (py3.12)" \
  -f required_status_checks.contexts[]="test (py3.13)" \
  -F enforce_admins=true \
  -f required_pull_request_reviews.dismiss_stale_reviews=true \
  -f required_pull_request_reviews.required_approving_review_count=0 \
  -f restrictions= \
  -f allow_force_pushes=false \
  -f allow_deletions=false \
  -f required_linear_history=true

echo "applied branch protection to ${REPO}:main"
