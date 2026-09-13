#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git
APP_DIR=${APP_DIR:-$HOME/boss-vao-lenh}
if [ ! -d "$APP_DIR/.git" ]; then
  git clone https://github.com/caubig96-ai/boss-vao-lenh.git "$APP_DIR"
fi
cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp -n .env.cloud.example .env || true
echo "Installed in $APP_DIR"
