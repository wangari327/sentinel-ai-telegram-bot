# SentinelAI Telegram Anti-Spam Bot

SentinelAI is a production-oriented Telegram moderation bot for groups and supergroups. It analyzes incoming messages with local rules, group training examples, similarity checks, and an OpenAI-compatible AI provider. It can delete high-confidence spam, optionally ban high-risk repeat violators, and send private admin review messages for suspicious/borderline content.

The bot is built for fast-moving Telegram spam campaigns: compromised accounts posting clickbait, phishing, porn-bait, fake reward links, suspicious bot-start links, invite scams, shortened URLs, and repeated channel promotions.

## Safe Defaults

Fresh deployments are deliberately conservative.

- Groups start in `monitor_only`.
- `setup_completed=false` until `/setup` confirms bot admin permissions.
- `REQUIRE_AUTHORIZED_CHATS=true` by default.
- The bot only works in authorized chats.
- Ban mode is disabled until an admin enables it in group settings.
- `DEMO_MODE=true` prevents delete/ban actions and reports what would happen.

## Authorized Chats Only

SentinelAI ignores every group unless one of these is true:

- The Telegram chat ID is listed in `AUTHORIZED_CHAT_IDS`.
- An `OWNER_ADMIN_IDS` user runs `/setup` in the group, which marks the group authorized in the database.
- `REQUIRE_AUTHORIZED_CHATS=false` is set intentionally.

Recommended production config:

```env
REQUIRE_AUTHORIZED_CHATS=true
AUTHORIZED_CHAT_IDS=-1001234567890,-1009876543210
OWNER_ADMIN_IDS=123456789
LEAVE_UNAUTHORIZED_CHATS=false
```

Use `LEAVE_UNAUTHORIZED_CHATS=true` if you want the bot to leave groups it was added to without authorization.

## Telegram Setup

1. Create a bot with [BotFather](https://t.me/BotFather).
2. Copy `BOT_TOKEN`.
3. Add the bot to an authorized group.
4. Promote the bot to admin.
5. Give it:
   - Delete messages
   - Ban/restrict users if ban mode will be used
6. Send `/setup` in the group.
7. Start with `/mode monitor_only` or `/mode normal`.
8. Train with examples and corrections.

## Commands

- `/start` - setup hint in private or group.
- `/help` - command summary.
- `/panel` - owner-only private button console.
- `/setup` - verify permissions and activate authorized group setup.
- `/status` - show authorization, mode, setup, and example counts.
- `/mode` - change between `normal`, `auto_delete`, `silent`, `monitor_only`, and `aggressive`.
- `/thresholds` - show group thresholds.
- `/train` - explain private forwarding/training.
- `/examples` - show spam/not-spam example counts.
- `/trust` - reply to a message to trust a user.
- `/untrust` - remove a trusted user.
- `/ban_on` - allow automatic bans for high-confidence high-risk spam.
- `/ban_off` - disable automatic bans while keeping delete/review behavior.
- `/allowdomain` - mark a domain safe for the group.
- `/blockdomain` - mark a domain blocked for the group.
- `/domains` - list configured domain rules.
- `/privacy` - explain stored data and retention.

Private owner commands:

- `/panel` - open the button console for stats, groups, support issues, requests, history, and tutorial status.
- `/authorize <chat_id>` - authorize a chat from private DM.
- `/deauthorize <chat_id>` - remove DB authorization for a chat.
- `/tutorial_save` - save a forwarded video/document as the default support tutorial.

## Modes

- `monitor_only`: do not delete or ban; report suspicious content.
- `normal`: delete high-confidence spam; send admin review for borderline content.
- `auto_delete`: delete high-confidence spam immediately.
- `silent`: delete high-confidence spam without admin notifications.
- `aggressive`: temporarily delete borderline suspicious content pending review.

Automatic bans are controlled separately from mode. Use `/ban_on` only after the bot has ban/restrict permission and you are comfortable with detections. Use `/ban_off` to keep deleting spam without banning users.

Admin notifications are private DM review messages with action buttons. The admin user must start the bot in private chat first, otherwise Telegram may block the DM.

## iBOX Support Assistant

When `SUPPORT_ENABLED=true`, SentinelAI also watches non-spam group messages for lightweight support intents: movie/show requests, download/play tutorial questions, missing episodes, broken links, banned/removed items, and playback complaints. It replies only when a message clearly looks like support traffic, then deletes its own support replies after `SUPPORT_REPLY_CLEANUP_SECONDS`.

If `TVWEB_DATABASE_URL` is configured, the bot searches the website `tv_shows` table and can steer users to iBOX TV results. If no match is found, it records the request so you can review demand later from `/panel`. Use a read-only database user for this connection where possible.

```env
SUPPORT_ENABLED=true
SUPPORT_REPLY_CLEANUP_SECONDS=180
TVWEB_DATABASE_URL=postgresql+psycopg://readonly:password@host:5432/tv_shows_db
TVWEB_SITE_BASE_URL=https://ibox-tv.com
TVWEB_ANIME_BASE_URL=https://anime.ibox-tv.com
TVWEB_MOVIES_BASE_URL=https://movies.ibox-tv.com
```

To save a tutorial, forward the video/document to the bot privately with `/tutorial_save` in the caption. When users ask how to download or play files, the bot sends the saved tutorial if available.

## AI Providers

OpenAI is the default provider because it is the simplest reliable production choice for structured JSON classification.

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your-openai-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.5-mini
OPENAI_ESCALATION_MODEL=gpt-5.5
```

### Affordable / Free Provider Choices

Recommended order for this bot:

- Cheapest reliable production path: `AI_PROVIDER=hcnsec` or `AI_PROVIDER=openai_compatible` with your hcnsec/NewAPI gateway, if its uptime and model list are good.
- Cheap official paid path: `AI_PROVIDER=deepseek` with `deepseek-v4-flash`.
- Free/dev path: `AI_PROVIDER=gemini` with Gemini Flash/Flash-Lite free tier.
- Experimental free router: OpenRouter free models through `AI_PROVIDER=openai_compatible`.
- Zero-cost local/testing path: `AI_PROVIDER=rules_only` or `AI_PROVIDER=mock`.

For hcnsec/NewAPI, do not hardcode the key. Put it in environment variables:

```env
AI_PROVIDER=hcnsec
AI_FALLBACK_PROVIDER=rules_only
HCNSEC_API_KEY=your-key-here
HCNSEC_BASE_URL=https://api.hcnsec.cn
HCNSEC_MODEL=deepseek-v4-flash
HCNSEC_PROVIDER_NAME=hcnsec
OPENAI_COMPATIBLE_USE_STRUCTURED_OUTPUT=false
```

If your gateway requires the OpenAI `/v1` prefix, use:

```env
HCNSEC_BASE_URL=https://api.hcnsec.cn/v1
```

For any OpenAI-compatible gateway:

```env
AI_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_API_KEY=your-key-here
OPENAI_COMPATIBLE_BASE_URL=https://openrouter.ai/api/v1
OPENAI_COMPATIBLE_MODEL=openrouter/free
OPENAI_COMPATIBLE_PROVIDER_NAME=openrouter
OPENAI_COMPATIBLE_USE_STRUCTURED_OUTPUT=false
```

Official DeepSeek:

```env
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Gemini can be used as an alternative or fallback:

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

Ollama/local models can be used with an OpenAI-compatible endpoint:

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b-instruct
```

Rules-only mode is always available for testing or emergency fallback:

```env
AI_PROVIDER=rules_only
AI_FALLBACK_PROVIDER=rules_only
```

## Cost Control

SentinelAI runs cheap checks before calling AI:

- trusted/admin skip rules
- empty/short harmless message skip
- allowed/blocked domain checks
- exact and similar training examples
- URL/t.me/obfuscation/porn-bait/crypto/reward feature extraction

Useful settings:

```env
AI_SCAN_ALL_MESSAGES=false
AI_SCAN_LINKS_ONLY=true
AI_TIMEOUT_SECONDS=6
AI_MAX_RETRIES=2
```

## Local Development

Create `.env` from `.env.example`, then run:

```bash
docker compose up --build
```

For local polling without a public webhook:

```bash
pip install -e ".[dev]"
AUTO_SET_WEBHOOK=false sentinel-ai-polling
```

Validate production-style environment variables before deployment:

```bash
sentinel-ai-config-check
```

## Production Webhook

Run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

Webhook endpoint:

```text
POST /telegram/webhook/{WEBHOOK_SECRET}
```

If `AUTO_SET_WEBHOOK=true`, startup registers:

```text
{WEBHOOK_BASE_URL}/telegram/webhook/{WEBHOOK_SECRET}
```

Manual webhook setup:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<WEBHOOK_BASE_URL>/telegram/webhook/<WEBHOOK_SECRET>"
```

`BOT_TOKEN` is never placed in your webhook URL.

## Deploy To VPS

The production VPS target is:

```text
Domain: antispam.ibox-tv.com
VPS IP: 20.164.220.8
OS: Ubuntu 24.04 LTS
```

The subdomain must have an `A` record pointing at the VPS IP. DNS is already expected to look like:

```text
Type: A
Name: antispam
Value: 20.164.220.8
```

VPS templates live in `deploy/`:

- `deploy/scripts/install_vps.sh` - one-off Ubuntu VPS installer.
- `deploy/vps.env.example` - production `.env` template with hcnsec/NewAPI defaults.
- `deploy/vps.docker-compose.yml` - Docker Compose override for Postgres, Redis, and bot.
- `deploy/nginx-sentinel-ai.conf` - Nginx reverse proxy example.
- `deploy/sentinel-ai.service` - systemd unit for non-Docker deployments.
- `deploy/VPS_DEPLOY.md` - step-by-step VPS guide.

### One-Off Install

Run this on the VPS as `root` or as a sudo-capable user:

```bash
cd /opt
git clone https://github.com/wangari327/sentinel-ai-telegram-bot.git
cd sentinel-ai-telegram-bot
bash deploy/scripts/install_vps.sh
```

The installer:

- installs Git, Docker, Nginx, Certbot, and required system packages
- clones or updates this repository into `/opt/sentinel-ai-telegram-bot`
- prompts for `BOT_TOKEN` and `HCNSEC_API_KEY`
- writes `/opt/sentinel-ai-telegram-bot/.env`
- creates random `WEBHOOK_SECRET` and `POSTGRES_PASSWORD` values
- starts Postgres, Redis, and the bot with `docker compose -f compose.vps.yml`
- configures Nginx for `antispam.ibox-tv.com`
- proxies Nginx to `127.0.0.1:8010` by default to avoid common port `8000` conflicts
- requests a Let's Encrypt HTTPS certificate
- checks `https://antispam.ibox-tv.com/health`

Non-interactive install:

```bash
cd /opt/sentinel-ai-telegram-bot
export BOT_TOKEN='paste-token-here'
export HCNSEC_API_KEY='paste-key-here'
export LETSENCRYPT_EMAIL='admin@ibox-tv.com'
bash deploy/scripts/install_vps.sh
```

If `.env` already exists, the installer keeps it. To intentionally rewrite it:

```bash
FORCE_ENV=true bash deploy/scripts/install_vps.sh
```

To skip Let's Encrypt during a dry run:

```bash
SKIP_CERTBOT=true bash deploy/scripts/install_vps.sh
```

If you prefer not to clone first, you can download the script directly. This depends on GitHub Raw being available from the VPS network:

```bash
curl --retry 5 --retry-delay 3 -fSL https://raw.githubusercontent.com/wangari327/sentinel-ai-telegram-bot/main/deploy/scripts/install_vps.sh -o install_vps.sh
bash install_vps.sh
```

### Required VPS Env

The installer writes these values to `/opt/sentinel-ai-telegram-bot/.env`:

```env
BOT_TOKEN=
WEBHOOK_BASE_URL=https://antispam.ibox-tv.com
WEBHOOK_SECRET=
APP_HOST_PORT=127.0.0.1:8010
AUTHORIZED_CHAT_IDS=-1001303757981,-1002370580254
OWNER_ADMIN_IDS=762308466
DEFAULT_NOTIFY_ADMIN_ID=762308466
HCNSEC_API_KEY=
```

Do not commit the real `.env`. If an API key or bot token was pasted into chat, logs, or Git history, rotate it with the provider and update only the VPS `.env`.

### VPS Operations

View logs:

```bash
cd /opt/sentinel-ai-telegram-bot
docker compose -f compose.vps.yml logs -f bot
```

Restart:

```bash
cd /opt/sentinel-ai-telegram-bot
docker compose -f compose.vps.yml restart bot
```

Update:

```bash
cd /opt/sentinel-ai-telegram-bot
git pull
docker compose -f compose.vps.yml up -d --build
docker compose -f compose.vps.yml logs -f bot
```

Health check:

```bash
curl https://antispam.ibox-tv.com/health
```

If port `8010` is also busy, set another local port in `.env` and reload Nginx:

```env
APP_HOST_PORT=127.0.0.1:8020
```

After deployment, add the bot to the authorized Telegram groups, promote it to admin, enable delete-message permission, and send `/setup` in each group. Start in `monitor_only`, then switch to `normal` when you are happy with detections:

```text
/status
/mode normal
```

The full VPS guide is in `deploy/VPS_DEPLOY.md`.

## Deploy To Heroku

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/YOUR_USERNAME/sentinel-ai-telegram-bot)

Steps:

1. Create a bot with BotFather.
2. Copy `BOT_TOKEN`.
3. Click the Heroku deploy button.
4. Fill `BOT_TOKEN`.
5. Fill `WEBHOOK_BASE_URL` with the Heroku app URL.
6. Fill `OPENAI_API_KEY` if using OpenAI.
7. Set `AUTHORIZED_CHAT_IDS` or `OWNER_ADMIN_IDS`.
8. Deploy.
9. Open `https://your-app-name.herokuapp.com/health`.
10. Add the bot to a Telegram group.
11. Promote it to admin with delete permission and ban/restrict permission if needed.
12. Send `/setup` in the group.
13. Start in `monitor_only` or `normal`.
14. Train with forwarded examples and review buttons.

Troubleshooting:

- Bot does not respond: check webhook URL, `BOT_TOKEN`, and Heroku logs.
- Bot cannot delete: promote bot to admin and enable delete messages.
- Bot cannot ban: enable ban/restrict users.
- Admin does not receive private alerts: admin must open the bot privately and press Start.
- AI not working: check `AI_PROVIDER` and provider API key, or switch to `AI_PROVIDER=rules_only`.
- Database error: ensure Heroku Postgres is installed and `DATABASE_URL` is present.
- App sleeps or delays: use an always-on Heroku plan for production groups.

## Training

Admins can train the bot by:

- Forwarding messages to the bot privately and choosing Spam or Not spam.
- Using admin review buttons.
- Marking false positives as Not spam.
- Saving group-local spam/not-spam examples.

Training examples store normalized text, short raw excerpts, domains, Telegram links, features, source, group ID, admin ID, and timestamps. Examples are group-local unless global sharing is explicitly enabled.

## Privacy

Stored data:

- group settings and authorization state
- trusted users and approved/blocked domains
- compact moderation event logs
- training examples
- pending review tokens
- user violation counts

Default retention:

- moderation logs: 30 days
- training examples: retained until deleted
- pending reviews: 7 days
- raw excerpts: truncated

The bot does not DM non-admin users with accusations and does not use one group’s private examples in another group unless global training is enabled.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The included tests cover URL extraction, t.me detection, obfuscation, domain allow/block behavior, trusted/admin skip behavior, callback authorization, threshold decisions, provider JSON parsing/fallback behavior, Heroku-style config, and webhook secret rejection.
