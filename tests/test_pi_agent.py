"""Tests for Raspberry Pi Agent service, token authentication, and dry-run safety."""

import os
import pytest
from unittest.mock import patch
import requests

from pi_agent.pi_server import app as pi_app, servo, monitor_state
from proctor.pi_client import RaspberryPiClient

TEST_TOKEN = "secret_test_token_12345"


@pytest.fixture
def pi_client():
    """Flask test client for pi_server."""
    pi_app.config["TESTING"] = True
    monitor_state.clear_history()
    with patch("pi_agent.pi_server.SHARED_TOKEN", TEST_TOKEN):
        with pi_app.test_client() as client:
            yield client


def test_pi_health_endpoint(pi_client):
    """Health check is open, reports dry-run mode, and indicates device status."""
    resp = pi_client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "online"
    assert data["dry_run"] is True
    assert data["servo_enabled"] is False


def test_pi_dashboard_page(pi_client):
    """GET / renders the HTML live dashboard without errors."""
    resp = pi_client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Raspberry Pi Proctor Monitor" in html
    assert "Servo Indicator" in html
    assert "Received Status History" in html


def test_pi_dashboard_api(pi_client):
    """GET /api/status returns live telemetry snapshot for dashboard polling."""
    resp = pi_client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "current_status" in data
    assert "event_type" in data
    assert "face_count" in data
    assert "servo" in data
    assert "history" in data


def test_pi_auth_missing(pi_client):
    """Requests without auth header return HTTP 401."""
    resp = pi_client.post(
        "/status",
        json={"status": "ALERT", "event_type": "FACE_ABSENT"},
    )
    assert resp.status_code == 401
    data = resp.get_json()
    assert "Unauthorized" in data["error"]


def test_pi_auth_invalid(pi_client):
    """Requests with wrong bearer token return HTTP 401."""
    resp = pi_client.post(
        "/status",
        headers={"Authorization": "Bearer invalid_secret_token"},
        json={"status": "ALERT", "event_type": "FACE_ABSENT"},
    )
    assert resp.status_code == 401


def test_pi_invalid_payload(pi_client):
    """Requests with non-JSON or invalid status string return HTTP 400."""
    # 1. Invalid status value
    resp = pi_client.post(
        "/status",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"status": "INVALID_STATUS_COMMAND"},
    )
    assert resp.status_code == 400
    assert "Invalid status field" in resp.get_json()["error"]

    # 2. Non-JSON payload
    resp = pi_client.post(
        "/status",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        data="raw string not json",
    )
    assert resp.status_code == 400


def test_pi_valid_status_dry_run(pi_client):
    """Valid status updates succeed, update dashboard state, and report dry-run simulation message."""
    # Test ALERT status
    resp = pi_client.post(
        "/status",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={
            "status": "ALERT",
            "event_type": "FACE_ABSENT",
            "face_count": 0,
            "explanation": "Test candidate absence",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["acknowledged"] is True
    assert data["received_status"] == "ALERT"
    assert "DRY-RUN SIMULATION" in data["servo_action"]

    # Verify dashboard state was updated
    api_resp = pi_client.get("/api/status")
    api_data = api_resp.get_json()
    assert api_data["current_status"] == "ALERT"
    assert api_data["event_type"] == "FACE_ABSENT"
    assert api_data["face_count"] == 0
    assert api_data["total_alerts"] == 1
    assert len(api_data["history"]) == 1

    # Test NORMAL status
    resp_norm = pi_client.post(
        "/status",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={
            "status": "NORMAL",
            "event_type": "NORMAL",
            "face_count": 1,
            "explanation": "Normal candidate present",
        },
    )
    assert resp_norm.status_code == 200
    assert resp_norm.get_json()["received_status"] == "NORMAL"

    # Verify history has 2 entries
    api_resp2 = pi_client.get("/api/status")
    api_data2 = api_resp2.get_json()
    assert api_data2["current_status"] == "NORMAL"
    assert len(api_data2["history"]) == 2


def test_pi_client_offline_graceful_handling():
    """RaspberryPiClient handles connection errors without throwing unhandled exceptions."""
    # Point to a guaranteed non-existent local port
    offline_client = RaspberryPiClient(
        base_url="http://127.0.0.1:59999",
        shared_token="dummy",
        timeout_sec=0.2,
        enabled=True,
    )

    # Health check should return False, not crash
    assert offline_client.check_health() is False
    assert offline_client.get_status().online is False

    # Status notification should return False, not crash
    assert offline_client.notify_status(status="ALERT", event_type="FACE_ABSENT") is False
    assert offline_client.get_status().online is False
