"""Fast tests for application, database health, and language metadata endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["model_status"] == "ready"
    assert data["model_name"] == "small"


def test_db_health_endpoint(client: TestClient) -> None:
    res = client.get("/health/db")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_languages_endpoint(client: TestClient) -> None:
    res = client.get("/api/languages")
    assert res.status_code == 200
    data = res.json()
    codes = {item["code"] for item in data["supported_languages"]}
    assert {"en", "hi", "hi-en"}.issubset(codes)
    assert "mixed" in data["script_mix_categories"]


def test_dashboard_html_served(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Speech to Text" in res.text
