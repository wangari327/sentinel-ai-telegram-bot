#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="sentinel-ai-telegram-bot"
APP_DIR="${APP_DIR:-/opt/${APP_NAME}}"
REPO_URL="${REPO_URL:-https://github.com/wangari327/sentinel-ai-telegram-bot.git}"
DOMAIN="${DOMAIN:-antispam.ibox-tv.com}"
EMAIL="${LETSENCRYPT_EMAIL:-}"
SKIP_CERTBOT="${SKIP_CERTBOT:-false}"
FORCE_ENV="${FORCE_ENV:-false}"
APP_HOST_PORT="${APP_HOST_PORT:-127.0.0.1:8010}"

log() {
  printf '\n[%s] %s\n' "$(date +'%H:%M:%S')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  elif need_cmd sudo; then
    sudo "$@"
  else
    die "This command needs root privileges. Re-run as root or install sudo."
  fi
}

current_owner() {
  if [[ "${EUID}" -eq 0 ]]; then
    printf '%s:%s' "${SUDO_USER:-root}" "${SUDO_USER:-root}"
  else
    printf '%s:%s' "$USER" "$USER"
  fi
}

prompt_secret() {
  local name="$1"
  local current="${!name:-}"
  if [[ -n "$current" ]]; then
    return
  fi
  read -r -s -p "Enter ${name}: " current
  printf '\n'
  [[ -n "$current" ]] || die "${name} is required"
  export "${name}=${current}"
}

prompt_value() {
  local name="$1"
  local default_value="$2"
  local current="${!name:-}"
  if [[ -n "$current" ]]; then
    return
  fi
  read -r -p "Enter ${name} [${default_value}]: " current
  current="${current:-$default_value}"
  [[ -n "$current" ]] || die "${name} is required"
  export "${name}=${current}"
}

prompt_optional() {
  local name="$1"
  local default_value="$2"
  local prompt="${3:-$name}"
  local current="${!name:-}"
  if [[ -n "$current" ]]; then
    return
  fi
  read -r -p "Enter ${prompt} [${default_value}]: " current
  current="${current:-$default_value}"
  export "${name}=${current}"
}

random_hex() {
  openssl rand -hex 32
}

random_password() {
  openssl rand -base64 32 | tr -d '=+/' | cut -c1-32
}

install_packages() {
  log "Installing system packages"
  as_root apt-get update
  as_root apt-get install -y ca-certificates curl git nginx openssl certbot python3-certbot-nginx

  if ! need_cmd docker; then
    log "Installing Docker"
    curl -fsSL https://get.docker.com | as_root sh
  fi

  as_root systemctl enable --now docker
}

clone_or_update_repo() {
  log "Preparing application directory at ${APP_DIR}"
  as_root mkdir -p "$(dirname "$APP_DIR")"
  as_root chown "$(current_owner)" "$(dirname "$APP_DIR")"

  if [[ -d "${APP_DIR}/.git" ]]; then
    git -C "$APP_DIR" pull --ff-only
  else
    git clone "$REPO_URL" "$APP_DIR"
  fi
}

write_env() {
  local env_file="${APP_DIR}/.env"
  if [[ -f "$env_file" && "$FORCE_ENV" != "true" ]]; then
    log ".env already exists; keeping it. Set FORCE_ENV=true to rewrite."
    return
  fi

  prompt_secret BOT_TOKEN
  prompt_secret HCNSEC_API_KEY
  prompt_value AUTHORIZED_CHAT_IDS "-1001303757981,-1002370580254"
  prompt_value OWNER_ADMIN_IDS "762308466"
  prompt_value DEFAULT_NOTIFY_ADMIN_ID "$OWNER_ADMIN_IDS"
  prompt_optional TVWEB_DATABASE_URL "" "TVWEB_DATABASE_URL from website DATABASE_URL, or blank"
  prompt_optional TMDB_BEARER_TOKEN "" "TMDB_BEARER_TOKEN from website env, or blank"
  prompt_optional TUTORIAL_DUMP_CHAT_ID "-1003743973576"
  prompt_optional SUPPORT_TONE "playful, lightly sarcastic, chatty, funny, helpful, and never rude"

  WEBHOOK_SECRET="${WEBHOOK_SECRET:-$(random_hex)}"
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_password)}"
  DATABASE_URL="postgresql+psycopg://sentinel:${POSTGRES_PASSWORD}@postgres:5432/sentinel"

  log "Writing ${env_file}"
  umask 077
  cat > "$env_file" <<EOF
BOT_TOKEN=${BOT_TOKEN}
WEBHOOK_BASE_URL=https://${DOMAIN}
WEBHOOK_SECRET=${WEBHOOK_SECRET}
AUTO_SET_WEBHOOK=true
AUTO_MIGRATE=true
DEMO_MODE=false
LOG_LEVEL=INFO
RETENTION_DAYS=30
APP_HOST_PORT=${APP_HOST_PORT}

POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DATABASE_URL=${DATABASE_URL}
REDIS_URL=redis://redis:6379/0

REQUIRE_AUTHORIZED_CHATS=true
AUTHORIZED_CHAT_IDS=${AUTHORIZED_CHAT_IDS}
OWNER_ADMIN_IDS=${OWNER_ADMIN_IDS}
DEFAULT_NOTIFY_ADMIN_ID=${DEFAULT_NOTIFY_ADMIN_ID}
LEAVE_UNAUTHORIZED_CHATS=false
DEFAULT_GROUP_MODE=monitor_only

AI_PROVIDER=hcnsec
AI_FALLBACK_PROVIDER=rules_only
AI_TIMEOUT_SECONDS=6
AI_MAX_RETRIES=2
AI_USE_STRUCTURED_OUTPUT=false
AI_ESCALATE_ON_UNSURE=true
AI_ENABLE_PROVIDER_FALLBACK=true

HCNSEC_API_KEY=${HCNSEC_API_KEY}
HCNSEC_BASE_URL=${HCNSEC_BASE_URL:-https://api.hcnsec.cn}
HCNSEC_MODEL=${HCNSEC_MODEL:-deepseek-v4-flash}
HCNSEC_PROVIDER_NAME=hcnsec
OPENAI_COMPATIBLE_USE_STRUCTURED_OUTPUT=false

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.5-mini
OPENAI_ESCALATION_MODEL=gpt-5.5

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

SUPPORT_ENABLED=true
SUPPORT_AI_INTENT_ENABLED=true
SUPPORT_AI_INTENT_THRESHOLD=0.68
SUPPORT_AI_INTENT_MAX_TEXT_CHARS=700
PRIVATE_SUPPORT_ENABLED=true
PRIVATE_ABUSE_SILENCE_AFTER=3
SUPPORT_AI_REPLIES=true
SUPPORT_TONE=${SUPPORT_TONE}
SUPPORT_REPLY_CLEANUP_SECONDS=86400
TVWEB_DATABASE_URL=${TVWEB_DATABASE_URL}
TVWEB_SITE_BASE_URL=https://ibox-tv.com
TVWEB_ANIME_BASE_URL=https://anime.ibox-tv.com
TVWEB_MOVIES_BASE_URL=https://movies.ibox-tv.com
TUTORIAL_DUMP_CHAT_ID=${TUTORIAL_DUMP_CHAT_ID}
TVWEB_CACHE_ENABLED=true
TVWEB_CACHE_REFRESH_ON_STARTUP=false
TVWEB_CACHE_REFRESH_INTERVAL_MINUTES=360
TVWEB_CACHE_REFRESH_TIMES=02:00,08:00,14:00,20:00
TVWEB_CACHE_REFRESH_LIMIT=5000
TMDB_METADATA_ENABLED=true
TMDB_BEARER_TOKEN=${TMDB_BEARER_TOKEN}
TMDB_BASE_URL=https://api.themoviedb.org/3
TMDB_LANGUAGE=en-US
TMDB_REGION=US
TMDB_TIMEOUT_SECONDS=5
TMDB_CACHE_TTL_SECONDS=21600

DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_PROVIDER_NAME=deepseek

OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b-instruct

SPAM_DELETE_THRESHOLD=0.88
SPAM_BAN_THRESHOLD=0.96
SUSPICIOUS_LOW_THRESHOLD=0.55
SUSPICIOUS_HIGH_THRESHOLD=0.87
AI_SCAN_ALL_MESSAGES=false
AI_SCAN_LINKS_ONLY=true
EOF
  chmod 600 "$env_file"
}

configure_compose() {
  log "Configuring Docker Compose"
  cp "${APP_DIR}/deploy/vps.docker-compose.yml" "${APP_DIR}/compose.vps.yml"
}

start_stack() {
  log "Building and starting containers"
  cd "$APP_DIR"
  as_root docker compose -f compose.vps.yml up -d --build
}

configure_nginx() {
  log "Configuring Nginx for ${DOMAIN}"
  as_root tee /etc/nginx/sites-available/sentinel-ai >/dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://${APP_HOST_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  as_root ln -sf /etc/nginx/sites-available/sentinel-ai /etc/nginx/sites-enabled/sentinel-ai
  as_root nginx -t
  as_root systemctl reload nginx
}

issue_certificate() {
  if [[ "$SKIP_CERTBOT" == "true" ]]; then
    log "Skipping Certbot because SKIP_CERTBOT=true"
    return
  fi
  log "Requesting HTTPS certificate"
  if [[ -n "$EMAIL" ]]; then
    as_root certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect
  else
    as_root certbot --nginx -d "$DOMAIN" --redirect
  fi
}

health_check() {
  log "Checking health endpoint"
  for _ in {1..12}; do
    if curl -fsS "https://${DOMAIN}/health" || curl -fsS "http://${APP_HOST_PORT}/health"; then
      printf '\n'
      return
    fi
    sleep 5
  done
  die "health endpoint did not become ready. Check: cd ${APP_DIR} && docker compose -f compose.vps.yml logs bot"
}

main() {
  [[ "$(uname -s)" == "Linux" ]] || die "Run this script on the Ubuntu VPS"
  install_packages
  clone_or_update_repo
  write_env
  configure_compose
  configure_nginx
  issue_certificate
  start_stack
  health_check
  log "Done. Add the bot to Telegram groups, promote it to admin, then run /setup."
}

main "$@"
