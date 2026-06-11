#!/usr/bin/env bash
# Sync goliath's schwab-agent checkout with origin/main and restart services.
# Run on goliath: ~/tmp/schwab/deploy/goliath/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/../.."

git fetch origin
git reset --hard origin/main
uv sync -q

systemctl --user restart schwab-oauth.service
systemctl --user restart schwab-stream-cache.service || true
systemctl --user status schwab-oauth.service --no-pager | head -5
echo "Deployed $(git rev-parse --short HEAD)"
