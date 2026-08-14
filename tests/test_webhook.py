from fastapi.testclient import TestClient

from app.main import app, dispatch_telegram_update_safely


def test_webhook_secret_rejection() -> None:
    with TestClient(app) as client:
        response = client.post("/telegram/webhook/wrong", json={})

    assert response.status_code == 404


async def test_dispatch_update_safely_acknowledges_invalid_payload() -> None:
    handled = await dispatch_telegram_update_safely(
        payload={"update_id": 123},
        bot_instance=object(),  # type: ignore[arg-type]
        dispatcher_instance=object(),  # type: ignore[arg-type]
    )

    assert not handled
