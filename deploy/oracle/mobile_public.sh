#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="boss-vao-lenh-cloud"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env.cloud"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

PORT="$(grep -E '^CLOUD_MOBILE_PORT=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
PORT="${PORT:-8765}"
PASSWORD="$(grep -E '^CLOUD_MOBILE_PASSWORD=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"

if [[ -z "$PASSWORD" || "$PASSWORD" == "change-this-password" ]]; then
  echo "STOP: set a private CLOUD_MOBILE_PASSWORD in $ENV_FILE first."
  exit 1
fi

if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -qi '^Status: active'; then
  sudo ufw allow "${PORT}/tcp"
fi

sudo systemctl restart "$SERVICE_NAME"
sleep 2

if ! curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/login" >/dev/null; then
  echo "Boss dashboard is not answering locally on port $PORT."
  echo "Check: journalctl -u $SERVICE_NAME -n 100 --no-pager"
  exit 1
fi

PUBLIC_IP="$(curl -4 -fsS --max-time 5 https://api.ipify.org || true)"
echo
echo "LOCAL CHECK: OK"
echo "PORT: $PORT"
if [[ -n "$PUBLIC_IP" ]]; then
  echo "IPHONE URL: http://${PUBLIC_IP}:${PORT}"
fi
echo
echo "If the iPhone cannot open it, add this Oracle Cloud Ingress rule:"
echo "  Source CIDR:       0.0.0.0/0"
echo "  IP Protocol:       TCP"
echo "  Destination Port:  $PORT"
echo
echo "Then open the URL in Safari and log in with CLOUD_MOBILE_PASSWORD."
echo "The cloud service keeps running when the iPhone and PC are off."
