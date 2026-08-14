# VPS Deployment

This guide deploys SentinelAI on a Linux VPS with Docker Compose or systemd. Keep real secrets only on the VPS in `/opt/sentinel-ai-telegram-bot/.env`.

## One-Off Installer

On a fresh Ubuntu 24.04 VPS, run this after logging in as `root` or as your normal sudo user:

```bash
cd /opt
git clone https://github.com/wangari327/sentinel-ai-telegram-bot.git
cd sentinel-ai-telegram-bot
bash deploy/scripts/install_vps.sh
```

The script installs prerequisites, clones or updates the repo, prompts for `BOT_TOKEN` and `HCNSEC_API_KEY`, writes `.env`, starts Docker Compose through `compose.vps.yml`, configures Nginx, requests HTTPS for `antispam.ibox-tv.com`, and checks `/health`. It uses `sudo` only when needed and proxies to `127.0.0.1:8010` by default.

Non-interactive example:

```bash
cd /opt/sentinel-ai-telegram-bot
export BOT_TOKEN='paste-token-here'
export HCNSEC_API_KEY='paste-key-here'
export TVWEB_DATABASE_URL='paste-website-DATABASE_URL-here'
export LETSENCRYPT_EMAIL='admin@ibox-tv.com'
bash deploy/scripts/install_vps.sh
```

If you already uploaded `.env` yourself, the script keeps it unless you run:

```bash
FORCE_ENV=true bash deploy/scripts/install_vps.sh
```

If GitHub Raw is healthy and you prefer a single downloaded file:

```bash
curl --retry 5 --retry-delay 3 -fSL https://raw.githubusercontent.com/wangari327/sentinel-ai-telegram-bot/main/deploy/scripts/install_vps.sh -o install_vps.sh
bash install_vps.sh
```

## 1. Prepare DNS And Server

Point a domain or subdomain to the VPS:

```text
antispam.ibox-tv.com -> 20.164.220.8
```

Install Docker and Nginx:

```bash
sudo apt update
sudo apt install -y git curl nginx certbot python3-certbot-nginx
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

Log out and back in after adding your user to the Docker group.

## 2. Clone The Repo

```bash
sudo mkdir -p /opt
sudo chown "$USER:$USER" /opt
git clone https://github.com/wangari327/sentinel-ai-telegram-bot.git /opt/sentinel-ai-telegram-bot
cd /opt/sentinel-ai-telegram-bot
```

## 3. Create The VPS `.env`

```bash
cp deploy/vps.env.example .env
nano .env
```

Fill at minimum:

```env
BOT_TOKEN=your-telegram-bot-token
WEBHOOK_BASE_URL=https://antispam.ibox-tv.com
WEBHOOK_SECRET=use-a-long-random-secret
AUTHORIZED_CHAT_IDS=-1001303757981,-1002370580254
OWNER_ADMIN_IDS=762308466
DEFAULT_NOTIFY_ADMIN_ID=762308466
HCNSEC_API_KEY=your-provider-key
TVWEB_DATABASE_URL=paste-the-website-DATABASE_URL-value-here
TUTORIAL_DUMP_CHAT_ID=-1003743973576
SUPPORT_AI_INTENT_ENABLED=true
SUPPORT_AI_INTENT_THRESHOLD=0.68
SUPPORT_AI_INTENT_MAX_TEXT_CHARS=700
PRIVATE_SUPPORT_ENABLED=true
PRIVATE_ABUSE_SILENCE_AFTER=3
SUPPORT_REPLY_CLEANUP_SECONDS=86400
TVWEB_CACHE_ENABLED=true
TVWEB_CACHE_REFRESH_ON_STARTUP=false
TVWEB_CACHE_REFRESH_INTERVAL_MINUTES=360
TVWEB_CACHE_REFRESH_TIMES=02:00,08:00,14:00,20:00
TVWEB_CACHE_REFRESH_LIMIT=5000
```

Generate a secret:

```bash
openssl rand -hex 32
```

Find your Telegram user ID with a bot such as `@userinfobot`. Find a group ID by adding the bot to the group and checking logs or using a trusted ID helper bot.

For iBOX lookup, copy the website `.env` value named `DATABASE_URL` into Sentinel as `TVWEB_DATABASE_URL`. Do not use the website Mongo or Redis variables for this feature. The bot can remind you through the owner-only private console: press Start in the bot DM, then tap Website DB or Support status.

`TUTORIAL_DUMP_CHAT_ID=-1003743973576` is the default dump channel. Make the bot an admin in that channel, then forward the tutorial video/document to the bot privately with `/tutorial_save` in the caption.

Sentinel group support lookups search the local iBOX catalog cache only, so normal chat traffic does not hammer the website database. By default, the bot does not refresh that cache on startup; it refreshes at the UTC times in `TVWEB_CACHE_REFRESH_TIMES`, then every `TVWEB_CACHE_REFRESH_INTERVAL_MINUTES` after a successful refresh. Use the private owner-console Refresh catalog and Support status buttons to refresh manually and see cache count, last refresh, and any refresh error.

With `SUPPORT_AI_INTENT_ENABLED=true`, Sentinel lets the configured AI provider decide whether fuzzy group messages are support-worthy instead of relying only on phrase parsing. Lower `SUPPORT_AI_INTENT_THRESHOLD` if it misses too much; raise it if it starts answering ordinary chatter.

With `PRIVATE_SUPPORT_ENABLED=true`, normal users can DM the bot for iBOX help and use Start-button shortcuts. Private spam, abusive messages, explicit bait, malicious code snippets, and unsupported media-only uploads are logged as private moderation events; after `PRIVATE_ABUSE_SILENCE_AFTER` strikes, Sentinel stops replying to that private user.

`SUPPORT_REPLY_CLEANUP_SECONDS=86400` keeps group support replies around for one day before Sentinel deletes its own messages. Use `0` if you want those support replies to stay forever.

Press Start in the bot DM as an owner admin to use the button console. Groups can be authorized, deauthorized, or removed from buttons; open support issues and requests can be marked Fixed or Dismissed. Fixed items leave the open dashboard and send a durable group update tagging the original reporter when possible. Starting a fresh `/start`, `/panel`, support, or training flow cleans up older open bot panels in that same private chat.

Duplicate support reports are merged before they reach the dashboard. Sentinel uses catalog matches, normalized title variants, and the configured AI provider to decide when reports such as "Fix Lioness" and "Lioness link expired" are the same underlying issue.

## 4. Docker Compose Deployment

Copy the VPS compose file into place:

```bash
cp deploy/vps.docker-compose.yml compose.vps.yml
```

Set a real database password in `.env`:

```env
POSTGRES_PASSWORD=replace-this-password
DATABASE_URL=postgresql+psycopg://sentinel:replace-this-password@postgres:5432/sentinel
```

This local Docker Postgres volume survives normal app updates and container rebuilds. It does not survive a full VPS reinstall unless you restore a backup. For reinstall-proof bot history, point `DATABASE_URL` at an external Postgres service or run scheduled `pg_dump` backups off the VPS. MongoDB is not a drop-in replacement for Sentinel's current SQL schema.

Start the stack:

```bash
docker compose -f compose.vps.yml up -d --build
docker compose -f compose.vps.yml logs -f bot
```

The app listens on `127.0.0.1:8010` by default on the host and `8000` inside the container.

## 5. Nginx And HTTPS

Copy the Nginx example and edit the domain:

```bash
sudo cp deploy/nginx-sentinel-ai.conf /etc/nginx/sites-available/sentinel-ai
sudo ln -s /etc/nginx/sites-available/sentinel-ai /etc/nginx/sites-enabled/sentinel-ai
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d antispam.ibox-tv.com
```

Check health:

```bash
curl https://antispam.ibox-tv.com/health
```

If `AUTO_SET_WEBHOOK=true`, the bot registers the webhook on startup:

```text
https://sentinel.example.com/telegram/webhook/<WEBHOOK_SECRET>
```

## 6. Telegram Group Setup

1. Add the bot to an authorized group.
2. Promote it to admin.
3. Enable delete messages.
4. Enable ban/restrict users only if you want ban mode.
5. Send `/setup`.
6. Confirm `/status`.
7. Start with `/mode monitor_only` or `/mode normal`.

## Optional: systemd Without Docker

Install Python and PostgreSQL/Redis yourself, then:

```bash
sudo useradd --system --home /opt/sentinel-ai-telegram-bot --shell /usr/sbin/nologin sentinel
sudo chown -R sentinel:sentinel /opt/sentinel-ai-telegram-bot
sudo -u sentinel python3.11 -m venv /opt/sentinel-ai-telegram-bot/.venv
sudo -u sentinel /opt/sentinel-ai-telegram-bot/.venv/bin/pip install -r /opt/sentinel-ai-telegram-bot/requirements.txt
sudo cp deploy/sentinel-ai.service /etc/systemd/system/sentinel-ai.service
sudo systemctl daemon-reload
sudo systemctl enable --now sentinel-ai
journalctl -u sentinel-ai -f
```

## Updating

```bash
cd /opt/sentinel-ai-telegram-bot
git pull
docker compose -f compose.vps.yml up -d --build
docker compose -f compose.vps.yml logs -f bot
```

## Secret Safety

Do not commit `.env`, API keys, bot tokens, webhook secrets, or database passwords. If a key was pasted into chat or logs, rotate it in the provider dashboard and update the VPS `.env`.
