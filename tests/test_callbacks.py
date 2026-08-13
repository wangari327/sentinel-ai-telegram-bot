import pytest

from app.bot.callbacks import (
    callback_user_is_authorized,
    make_signed_token,
    verify_signed_token,
)


def test_signed_callback_token_roundtrip() -> None:
    token = make_signed_token(event_id=42, admin_user_id=7, secret="secret", ttl_seconds=60)
    claims = verify_signed_token(token, secret="secret")

    assert claims.event_id == 42
    assert claims.admin_user_id == 7


def test_signed_callback_token_rejects_tampering() -> None:
    token = make_signed_token(event_id=42, admin_user_id=7, secret="secret", ttl_seconds=60)
    tampered = token.replace(".", "x.", 1)

    with pytest.raises(ValueError):
        verify_signed_token(tampered, secret="secret")


def test_admin_only_callback_authorization() -> None:
    assert callback_user_is_authorized(
        callback_user_id=7,
        pending_admin_user_id=7,
        is_group_admin=False,
        owner_admin_ids=set(),
    )
    assert not callback_user_is_authorized(
        callback_user_id=8,
        pending_admin_user_id=7,
        is_group_admin=False,
        owner_admin_ids=set(),
    )
