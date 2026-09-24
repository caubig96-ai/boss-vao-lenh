#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="boss-vao-lenh-cloud"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$ROOT/.venv"
ENV_FILE="$ROOT/.env.cloud"
EXAMPLE_ENV="$ROOT/.env.cloud.example"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_USER="${SUDO_USER:-$USER}"
RUN_GROUP="$(id -gn "$RUN_USER")"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

printf '\n=== Boss Vao Lenh CLOUD V4.2 installer ===\n'
printf 'Repo: %s\n' "$ROOT"
printf 'User: %s\n\n' "$RUN_USER"

if ! command -v sudo >/dev/null 2>&1; then
  echo "ERROR: sudo is required."
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y     python3 python3-venv python3-pip git ca-certificates curl
else
  echo "ERROR: This installer currently supports Ubuntu/Debian images with apt-get."
  exit 1
fi

if [[ ! -d "$VENV" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$ROOT/requirements.txt"

mkdir -p "$ROOT/data" "$ROOT/logs"
chown -R "$RUN_USER:$RUN_GROUP" "$ROOT/data" "$ROOT/logs" "$VENV" || true

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$EXAMPLE_ENV" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  chown "$RUN_USER:$RUN_GROUP" "$ENV_FILE" || true
  echo
  echo "Created $ENV_FILE"
  echo "IMPORTANT: fill Telegram, Prediction API and MOBILE_PASSWORD values."
fi

sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Boss Vao Lenh Cloud V4.2 Always On
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
Environment=CLOUD_ENV_FILE=$ENV_FILE
ExecStart=$VENV/bin/python $ROOT/cloud_v3.py
Restart=always
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGTERM
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

TOKEN_VALUE="$(grep -E '^CLOUD_TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
CHAT_VALUE="$(grep -E '^CLOUD_TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
MOBILE_ENABLED="$(grep -E '^CLOUD_MOBILE_ENABLED=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
MOBILE_PORT="$(grep -E '^CLOUD_MOBILE_PORT=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
MOBILE_PORT="${MOBILE_PORT:-8765}"

if [[ -n "$TOKEN_VALUE" && -n "$CHAT_VALUE" ]]; then
  sudo systemctl restart "$SERVICE_NAME"
  sleep 3
  sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
else
  echo
  echo "Service installed but not started because .env.cloud is missing Telegram credentials."
  echo "Edit it now: nano $ENV_FILE"
  echo "Then start: sudo systemctl restart $SERVICE_NAME"
fi

if [[ "$MOBILE_ENABLED" != "0" && "$MOBILE_ENABLED" != "false" ]]; then
  if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -qi '^Status: active'; then
    sudo ufw allow "${MOBILE_PORT}/tcp" >/dev/null || true
    echo "UFW: opened TCP $MOBILE_PORT"
  fi
  PUBLIC_IP="$(curl -4 -fsS --max-time 5 https://api.ipify.org || true)"
  echo
  echo "=== IPHONE REMOTE DASHBOARD ==="
  if [[ -n "$PUBLIC_IP" ]]; then
    echo "Candidate URL: http://${PUBLIC_IP}:${MOBILE_PORT}"
  else
    echo "Public IP could not be detected automatically."
  fi
  echo "Oracle Cloud still needs an Ingress rule: TCP destination port ${MOBILE_PORT} from your chosen source."
  echo "For quick access use 0.0.0.0/0; for tighter security restrict the source where practical."
  echo "Login uses CLOUD_MOBILE_PASSWORD from .env.cloud."
fi

echo
echo "Boss runs under systemd even when the PC and iPhone are OFF."
echo "Useful commands:"
echo "  status: sudo systemctl status $SERVICE_NAME"
echo "  logs:   journalctl -u $SERVICE_NAME -f"
echo "  file:   tail -f $ROOT/logs/cloud-v4.log"
echo "  mobile: bash $ROOT/deploy/oracle/mobile_public.sh"
echo "  update: bash $ROOT/deploy/oracle/update.sh"
