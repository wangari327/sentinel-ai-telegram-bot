#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="sentinel-ai-telegram-bot"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.vps.yml}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8010/health}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-8}"
LOG_TAG="${LOG_TAG:-sentinel-ai-watchdog}"

log() {
  logger -t "$LOG_TAG" "$*"
  printf '[%s] %s\n' "$(date -Is)" "$*"
}

if curl -fsS --max-time "$TIMEOUT_SECONDS" "$HEALTH_URL" >/dev/null; then
  exit 0
fi

log "health check failed at ${HEALTH_URL}; restarting bot container"
cd "$APP_DIR"
docker compose -f "$COMPOSE_FILE" restart bot
