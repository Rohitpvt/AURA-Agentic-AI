"""Tests for /v1/cloud-keys and /v1/cloud-keys/status endpoints."""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from openjarvis.server.routes import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AURA_HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_cloud_keys_status_and_crud(client, tmp_path):
    # Initial status
    res = client.get("/v1/cloud-keys/status")
    assert res.status_code == 200
    status = res.json()
    assert "GEMINI_API_KEY" in status
    assert "OPENAI_API_KEY" in status

    # Save a key
    save_res = client.post(
        "/v1/cloud-keys",
        json={"key_name": "OPENROUTER_API_KEY", "key_value": "sk-or-test1234"},
    )
    assert save_res.status_code == 200
    assert save_res.json()["is_set"] is True

    # Check status updated
    res2 = client.get("/v1/cloud-keys/status")
    assert res2.status_code == 200
    assert res2.json()["OPENROUTER_API_KEY"] is True

    # Delete key
    del_res = client.delete("/v1/cloud-keys/OPENROUTER_API_KEY")
    assert del_res.status_code == 200

    # Status reflects deletion
    res3 = client.get("/v1/cloud-keys/status")
    assert res3.status_code == 200
    assert res3.json()["OPENROUTER_API_KEY"] is False
