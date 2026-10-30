"""Tests for Flask Dashboard routes and REST API."""

import pytest
from app import create_app
from proctor.camera import CameraManager


@pytest.fixture
def test_app():
    """Create Flask application configured with synthetic camera for isolated tests."""
    # Reset singleton camera to avoid leftover state
    CameraManager.reset_instance()
    app = create_app(synthetic_camera=True)
    app.config["TESTING"] = True
    yield app
    CameraManager.reset_instance()


@pytest.fixture
def client(test_app):
    return test_app.test_client()


def test_dashboard_index_route(client):
    """Index page returns 200 OK and includes human-review disclaimer."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Exam Proctoring System" in html
    assert "Academic Prototype Notice" in html
    assert "human proctor review" in html


def test_api_status_route(client):
    """Status API returns telemetry schema."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "is_active" in data
    assert "current_status" in data
    assert "face_count" in data
    assert "camera" in data
    assert "pi" in data
    assert "event_counts" in data


def test_api_session_lifecycle(client):
    """Session can be started and stopped via API."""
    start_resp = client.post("/api/session/start")
    assert start_resp.status_code == 200
    assert start_resp.get_json()["success"] is True

    stop_resp = client.post("/api/session/stop")
    assert stop_resp.status_code == 200
    assert stop_resp.get_json()["success"] is True


def test_evidence_directory_traversal_protection(client):
    """Attempts to traverse directory paths via evidence endpoint are blocked."""
    resp = client.get("/evidence/../../etc/passwd")
    assert resp.status_code in (400, 404)


def test_camera_listing_and_selection(client):
    """Camera endpoint lists cameras and supports dynamic switching."""
    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "cameras" in data
    assert "active_index" in data

    # Switch camera endpoint
    switch_resp = client.post("/api/camera/select", json={"camera_index": 0})
    assert switch_resp.status_code == 200
    switch_data = switch_resp.get_json()
    assert "success" in switch_data
    assert switch_data["active_index"] == 0

