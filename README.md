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
- `/ping` - plain liveness check; useful when Telegram goes quiet.
- `/setup` - verify permissions and activate authorized group setup.
- `/status` - show authorization, mode, setup, and example counts.
- `/debug_group` - admin-only group diagnostics for authorization, mode, and bot permissions.
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

Private owner controls:

- Press Start in the bot DM, or send `/start`, to open the button console for stats, groups, support issues, requests, history, tutorial status, website DB status, cache refresh, and backups.
- The owner console is button-first: the Groups view can authorize, deauthorize, or remove seen chats; Issues and Requests views can mark items fixed or dismiss them.
- Console sub-pages include a Back home button, and Spam history only shows suspicious/detected/reviewable moderation items instead of harmless allowed title chatter.
- New `/start`, `/panel`, support, and training flows clean up older open bot panels in that same private chat before posting the fresh buttons.
- `/panel` - fallback command to reopen the same button console if the message gets buried.
- `/authorize <chat_id>` - authorize a chat from private DM.
- `/deauthorize <chat_id>` - remove DB authorization for a chat.
- `/tutorial_save` - save a forwarded video/document as the default support tutorial.
- `/tvweb_config` - show exactly which website env value to paste for iBOX lookup.
- `/support_status` - show iBOX support config and local catalog cache status.
- `/refresh_tvweb_cache` - owner-only manual refresh for the local iBOX catalog cache.
- `/persistence` or `/backups` - show how bot data survives updates and reinstalls.

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

If `TMDB_BEARER_TOKEN` is configured, Sentinel checks TMDB before logging release-date and missing-episode style messages. Future movies, unaired seasons, unaired episodes, and unconfirmed seasons get a direct availability reply instead of noisy dashboard tickets. This is especially useful for messages like "Silo season 3 episode 8 missing" when the episode has not aired yet.

Repeated support reports are merged instead of duplicated. Sentinel first checks catalog IDs and normalized title variants, then asks the configured AI provider whether fuzzy reports describe the same underlying show/movie/anime and the same practical issue. The dashboard shows the occurrence count so you can see when a broken link or request is getting noisy.

From the website `.env`, use the value named `DATABASE_URL` and add it to Sentinel as `TVWEB_DATABASE_URL`. Copy `TMDB_BEARER_TOKEN` from the same website env for release metadata. Do not use `MONGO_URI_1`, `MONGO_URI_2`, `MONGO_DB_NAME`, `MONGO_COL_NAME`, `REDIS_URL`, or `TMDB_BACKFILL_TOKENS` for the bot runtime. The private owner command `/tvweb_config` prints this reminder from the bot.

```env
SUPPORT_ENABLED=true
SUPPORT_AI_INTENT_ENABLED=true
SUPPORT_AI_INTENT_THRESHOLD=0.68
SUPPORT_AI_INTENT_MAX_TEXT_CHARS=700
PRIVATE_SUPPORT_ENABLED=true
PRIVATE_ABUSE_SILENCE_AFTER=3
SUPPORT_AI_REPLIES=true
SUPPORT_TONE=playful, lightly sarcastic, chatty, funny, helpful, and never rude
SUPPORT_REPLY_CLEANUP_SECONDS=86400
TVWEB_DATABASE_URL=postgresql+psycopg://readonly:password@host:5432/tv_shows_db
TVWEB_SITE_BASE_URL=https://ibox-tv.com
TVWEB_ANIME_BASE_URL=https://anime.ibox-tv.com
TVWEB_MOVIES_BASE_URL=https://movies.ibox-tv.com
TUTORIAL_DUMP_CHAT_ID=-1003743973576
TVWEB_CACHE_ENABLED=true
TVWEB_CACHE_REFRESH_ON_STARTUP=false
TVWEB_CACHE_REFRESH_INTERVAL_MINUTES=360
TVWEB_CACHE_REFRESH_TIMES=02:00,08:00,14:00,20:00
TVWEB_CACHE_REFRESH_LIMIT=5000
TMDB_METADATA_ENABLED=true
TMDB_BEARER_TOKEN=
TMDB_BASE_URL=https://api.themoviedb.org/3
TMDB_LANGUAGE=en-US
TMDB_REGION=US
TMDB_TIMEOUT_SECONDS=5
TMDB_CACHE_TTL_SECONDS=21600
```

To save a tutorial, forward the video/document to the bot privately with `/tutorial_save` in the caption. When `TUTORIAL_DUMP_CHAT_ID` is set, Sentinel also copies that tutorial into the dump channel so the media stays easy to audit. When users ask how to download or play files, the bot sends the saved tutorial if available.

Support intent is AI-assisted when `SUPPORT_AI_INTENT_ENABLED=true`. The rule parser still catches obvious cases quickly, but when wording is fuzzy the AI decides whether the message is a title request, broken/missing/banned/playback issue, tutorial/how-to question, or ordinary chatter. `SUPPORT_AI_INTENT_THRESHOLD` controls how confident the AI must be before Sentinel replies or logs anything.

Private user support is enabled with `PRIVATE_SUPPORT_ENABLED=true`. Normal users who press Start in the bot DM get iBOX support buttons and can ask the same search/request/issue/tutorial questions privately. Private spam, abusive messages, explicit bait, malicious code snippets, and unsupported media-only uploads are logged as private moderation events; after `PRIVATE_ABUSE_SILENCE_AFTER` strikes, Sentinel stops replying to that private user.

`SUPPORT_REPLY_CLEANUP_SECONDS=86400` keeps group support replies around for one day before Sentinel deletes its own messages. Set it to `0` to disable cleanup, or lower it if a group gets noisy.

When you mark an issue or request as Fixed from the owner dashboard, Sentinel removes it from the open dashboard and posts a fresh group update tagging the original reporter when Telegram allows it. Those resolution notices are not auto-deleted, so people can see that the issue was handled. Dismiss clears the dashboard item without notifying the group.

Support answers are factual first, then AI-polished when `SUPPORT_AI_REPLIES=true` and your configured `AI_PROVIDER` supports chat completions. If the provider fails, the bot falls back to the plain factual reply.

Sentinel does not query the website database for every group message. Group messages search the local `tvweb_catalog_items` cache only. By default, the bot does not refresh that cache on startup; this keeps small VPS instances responsive after deploys. It refreshes at any UTC times listed in `TVWEB_CACHE_REFRESH_TIMES`, then every `TVWEB_CACHE_REFRESH_INTERVAL_MINUTES` after a successful refresh. Use the private owner-console buttons to refresh the catalog or view status; `/refresh_tvweb_cache`, `/tvweb_config`, and `/support_status` remain as fallback commands.

TMDB metadata is fetched only for support messages that look like requests, issues, or release questions, and results are cached in memory for `TMDB_CACHE_TTL_SECONDS`. It does not replace iBOX search; it helps Sentinel decide whether a user is asking for something unavailable, unaired, or genuinely missing from your catalog.

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

With `AI_SCAN_LINKS_ONLY=true`, Sentinel still escalates severe no-link risk text such as adult clickbait lures, crypto scams, fake rewards, and login phishing language. This keeps costs low without letting obvious text-only campaigns slide into "ask admin" purgatory.

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
- installs a lightweight cron watchdog that restarts the bot if local `/health` stops responding

Non-interactive install:

```bash
cd /opt/sentinel-ai-telegram-bot
export BOT_TOKEN='paste-token-here'
export HCNSEC_API_KEY='paste-key-here'
export TVWEB_DATABASE_URL='paste-website-DATABASE_URL-here'
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
TELEGRAM_WEBHOOK_MAX_CONNECTIONS=10
TELEGRAM_DROP_PENDING_UPDATES_ON_STARTUP=true
APP_HOST_PORT=127.0.0.1:8010
AUTHORIZED_CHAT_IDS=-1001303757981,-1002370580254
OWNER_ADMIN_IDS=762308466
DEFAULT_NOTIFY_ADMIN_ID=762308466
HCNSEC_API_KEY=
TVWEB_DATABASE_URL=
TMDB_BEARER_TOKEN=
TUTORIAL_DUMP_CHAT_ID=-1003743973576
SUPPORT_AI_INTENT_ENABLED=true
SUPPORT_AI_INTENT_THRESHOLD=0.68
SUPPORT_AI_INTENT_MAX_TEXT_CHARS=700
PRIVATE_SUPPORT_ENABLED=true
PRIVATE_ABUSE_SILENCE_AFTER=3
TVWEB_CACHE_ENABLED=true
TVWEB_CACHE_REFRESH_ON_STARTUP=false
TVWEB_CACHE_REFRESH_INTERVAL_MINUTES=360
TVWEB_CACHE_REFRESH_TIMES=02:00,08:00,14:00,20:00
TVWEB_CACHE_REFRESH_LIMIT=5000
TMDB_METADATA_ENABLED=true
TMDB_CACHE_TTL_SECONDS=21600
```

Do not commit the real `.env`. If an API key or bot token was pasted into chat, logs, or Git history, rotate it with the provider and update only the VPS `.env`.

For the website integration, paste the website `.env` value named `DATABASE_URL` into `TVWEB_DATABASE_URL`. Sentinel normalizes `postgresql://...` to `postgresql+psycopg://...`, so either prefix is fine. For release and season/episode metadata, paste the website `.env` value named `TMDB_BEARER_TOKEN` into Sentinel as `TMDB_BEARER_TOKEN`; do not use `TMDB_BACKFILL_TOKENS`.

The default Docker Postgres volume survives container rebuilds and repo updates. It does not survive a full VPS reinstall unless you restore a backup. For reinstall-proof bot data, use an external Postgres `DATABASE_URL` or schedule off-VPS `pg_dump` backups; MongoDB is not used by the current Sentinel schema.

`TELEGRAM_DROP_PENDING_UPDATES_ON_STARTUP=true` is intentional for this moderation bot. If the VPS is down for a while, Telegram may queue hundreds of old group messages. Dropping pending updates on restart prevents Sentinel from replaying stale chat history, spamming users, and burning AI quota. `TELEGRAM_WEBHOOK_MAX_CONNECTIONS=10` also keeps Telegram from flooding the app immediately after downtime.

### VPS Operations

View logs:

```bash
cd /opt/sentinel-ai-telegram-bot
docker compose -f compose.vps.yml logs -f bot
```

Fast silence check:

```bash
cd /opt/sentinel-ai-telegram-bot
docker compose -f compose.vps.yml ps
curl -sS https://antispam.ibox-tv.com/health
BOT_TOKEN="$(grep -m1 '^BOT_TOKEN=' .env | cut -d= -f2- | tr -d '\r')"
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getMe"
curl -sS "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
docker compose -f compose.vps.yml logs --tail=200 bot
```

Then send `/ping` to the bot in private chat and watch the logs. If `/ping` does not create a
`Telegram webhook update received` line, Telegram is not reaching this app instance. Check
`getWebhookInfo.last_error_message`, DNS/HTTPS, Nginx, and whether the webhook URL points to
`https://antispam.ibox-tv.com/telegram/webhook/<WEBHOOK_SECRET>`.

If `/ping` works in private but ordinary group messages are silent, send `/debug_group` in the
group. If slash commands work but normal group messages never create group-result logs, disable
BotFather privacy mode for the bot with BotFather's `/setprivacy` command. Also confirm the bot is
an admin with delete permission and that the group is authorized.

The VPS installer also creates `/etc/cron.d/sentinel-ai-watchdog`. Every two minutes it checks
`http://127.0.0.1:8010/health`; if the endpoint fails, it restarts only the bot container and logs
the event with the `sentinel-ai-watchdog` tag.

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
