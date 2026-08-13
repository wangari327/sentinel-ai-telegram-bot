# VPS Deployment

This guide deploys SentinelAI on a Linux VPS with Docker Compose or systemd. Keep real secrets only on the VPS in `/opt/sentinel-ai-telegram-bot/.env`.

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
```

Generate a secret:

```bash
openssl rand -hex 32
```

Find your Telegram user ID with a bot such as `@userinfobot`. Find a group ID by adding the bot to the group and checking logs or using a trusted ID helper bot.

## 4. Docker Compose Deployment

Copy the VPS compose file into place:

```bash
cp deploy/vps.docker-compose.yml docker-compose.override.yml
```

Set a real database password in `.env`:

```env
POSTGRES_PASSWORD=replace-this-password
DATABASE_URL=postgresql+psycopg://sentinel:replace-this-password@postgres:5432/sentinel
```

Start the stack:

```bash
docker compose up -d --build
docker compose logs -f bot
```

The app listens on `127.0.0.1:8000`.

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
docker compose up -d --build
docker compose logs -f bot
```

## Secret Safety

Do not commit `.env`, API keys, bot tokens, webhook secrets, or database passwords. If a key was pasted into chat or logs, rotate it in the provider dashboard and update the VPS `.env`.
