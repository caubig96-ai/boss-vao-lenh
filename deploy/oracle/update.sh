#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="boss-vao-lenh-cloud"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$ROOT/.venv"

cd "$ROOT"

echo "=== Updating Boss Vao Lenh CLOUD ==="

git fetch origin main
git checkout main
git pull --ff-only origin main

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -r requirements.txt
"$VENV/bin/python" -m unittest discover -s tests -v

sudo systemctl restart "$SERVICE_NAME"
sleep 2
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true

echo
echo "Updated to: $(git rev-parse --short HEAD)"
echo "Logs: journalctl -u $SERVICE_NAME -f"
