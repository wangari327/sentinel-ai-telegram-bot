from pathlib import Path


def test_vps_compose_builds_from_repo_root() -> None:
    compose = Path("deploy/vps.docker-compose.yml").read_text(encoding="utf-8")

    assert "build: ." in compose
    assert '"127.0.0.1:8000:8000"' in compose


def test_install_script_uses_expected_domain_and_keeps_existing_env() -> None:
    script = Path("deploy/scripts/install_vps.sh").read_text(encoding="utf-8")

    assert "DOMAIN=\"${DOMAIN:-antispam.ibox-tv.com}\"" in script
    assert ".env already exists; keeping it" in script
    assert "FORCE_ENV=true" in script
