from pathlib import Path


def test_vps_compose_builds_from_repo_root() -> None:
    compose = Path("deploy/vps.docker-compose.yml").read_text(encoding="utf-8")

    assert "build: ." in compose
    assert '"${APP_HOST_PORT:-127.0.0.1:8010}:8000"' in compose
    assert "healthcheck:" in compose
    assert "http://127.0.0.1:8000/health" in compose


def test_install_script_uses_expected_domain_and_keeps_existing_env() -> None:
    script = Path("deploy/scripts/install_vps.sh").read_text(encoding="utf-8")

    assert 'DOMAIN="${DOMAIN:-antispam.ibox-tv.com}"' in script
    assert ".env already exists; keeping it" in script
    assert "FORCE_ENV=true" in script
    assert 'APP_HOST_PORT="${APP_HOST_PORT:-127.0.0.1:8010}"' in script
    assert "docker compose -f compose.vps.yml up -d --build" in script
    assert "install_watchdog" in script
    assert "TELEGRAM_DROP_PENDING_UPDATES_ON_STARTUP=true" in script
    assert "prompt_optional TVWEB_DATABASE_URL" in script
    assert "prompt_optional TMDB_BEARER_TOKEN" in script
    assert "TUTORIAL_DUMP_CHAT_ID=${TUTORIAL_DUMP_CHAT_ID}" in script
    assert "SUPPORT_AI_REPLIES=true" in script
    assert "SUPPORT_REPLY_CLEANUP_SECONDS=86400" in script
    assert "TVWEB_CACHE_REFRESH_ON_STARTUP=false" in script
    assert "TVWEB_CACHE_REFRESH_INTERVAL_MINUTES=360" in script
    assert "TMDB_BEARER_TOKEN=${TMDB_BEARER_TOKEN}" in script


def test_vps_watchdog_restarts_unhealthy_bot() -> None:
    script = Path("deploy/scripts/watchdog_vps.sh").read_text(encoding="utf-8")

    assert "curl -fsS" in script
    assert 'docker compose -f "$COMPOSE_FILE" restart bot' in script
    assert "http://127.0.0.1:8010/health" in script
