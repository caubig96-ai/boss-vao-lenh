#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-$HOME/boss-vao-lenh}
cd "$APP_DIR"
git fetch origin
git reset --hard origin/main
. .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart boss-vao-lenh 2>/dev/null || true
echo "Updated to $(git rev-parse --short HEAD)"
