from fastapi.testclient import TestClient

from app.main import app


def test_webhook_secret_rejection() -> None:
    with TestClient(app) as client:
        response = client.post("/telegram/webhook/wrong", json={})

    assert response.status_code == 404
