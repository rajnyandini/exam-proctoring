"""Tests for proctoring state machine, monotonic thresholds, and duplicate event suppression."""

from unittest.mock import MagicMock
import numpy as np
import pytest

from proctor.camera import CameraManager
from proctor.face_detector import FaceDetector
from proctor.event_logger import EventLogger
from proctor.pi_client import RaspberryPiClient
from proctor.monitoring import MonitoringService


@pytest.fixture
def mock_monitoring(tmp_path):
    """Fixture providing a MonitoringService with mock camera and pi client."""
    db_file = tmp_path / "test_monitor.db"
    evidence_dir = tmp_path / "evidence"

    cam = MagicMock(spec=CameraManager)
    cam.fps = 15
    cam.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))

    detector = MagicMock(spec=FaceDetector)
    logger_svc = EventLogger(db_path=db_file, evidence_dir=evidence_dir)
    pi_client = MagicMock(spec=RaspberryPiClient)

    service = MonitoringService(
        camera=cam,
        detector=detector,
        logger_service=logger_svc,
        pi_client=pi_client,
        face_absence_threshold_sec=5.0,
        multiple_faces_threshold_sec=2.0,
        camera_error_threshold_sec=3.0,
    )
    service.session_id = "test_session"
    return service, logger_svc, pi_client


def test_normal_condition(mock_monitoring):
    """1 face detected returns NORMAL and clears timers."""
    service, logger_svc, pi_client = mock_monitoring
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    status, is_alert = service._update_temporal_state(face_count=1, frame=frame, now_mono=10.0)

    assert status == "NORMAL"
    assert is_alert is False
    assert service._active_anomaly is None
    assert len(logger_svc.get_recent_events()) == 0


def test_face_absence_threshold_and_suppression(mock_monitoring):
    """0 faces below 5.0s yields warning; at >= 5.0s yields alert and suppresses duplicates."""
    service, logger_svc, pi_client = mock_monitoring
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    # T=0.0: First missing face frame
    status, is_alert = service._update_temporal_state(face_count=0, frame=frame, now_mono=0.0)
    assert "WARNING" in status
    assert is_alert is False
    assert len(logger_svc.get_recent_events()) == 0

    # T=4.5: Still below 5.0s threshold
    status, is_alert = service._update_temporal_state(face_count=0, frame=frame, now_mono=4.5)
    assert "WARNING" in status
    assert is_alert is False
    assert len(logger_svc.get_recent_events()) == 0

    # T=5.1: Exceeds 5.0s threshold -> Alert triggered and event logged
    status, is_alert = service._update_temporal_state(face_count=0, frame=frame, now_mono=5.1)
    assert is_alert is True
    assert "ALERT: FACE ABSENT" in status
    assert service._active_anomaly == "FACE_ABSENT"

    events = logger_svc.get_recent_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "FACE_ABSENT"
    pi_client.notify_status.assert_called_with(
        status="ALERT",
        event_type="FACE_ABSENT",
        face_count=0,
        explanation=events[0]["explanation"],
    )

    # T=7.0: Condition persists -> DUPLICATE EVENT MUST BE SUPPRESSED
    status, is_alert = service._update_temporal_state(face_count=0, frame=frame, now_mono=7.0)
    assert is_alert is True
    assert len(logger_svc.get_recent_events()) == 1, "Duplicate event was not suppressed!"


def test_face_absence_reset_and_retrigger(mock_monitoring):
    """When a face returns, condition clears; subsequent absence retriggers a new event."""
    service, logger_svc, pi_client = mock_monitoring
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    # Trigger first absence alert at T=5.1
    service._update_temporal_state(face_count=0, frame=frame, now_mono=0.0)
    service._update_temporal_state(face_count=0, frame=frame, now_mono=5.1)
    assert len(logger_svc.get_recent_events()) == 1

    # Candidate returns at T=8.0 (1 face)
    status, is_alert = service._update_temporal_state(face_count=1, frame=frame, now_mono=8.0)
    assert status == "NORMAL"
    assert is_alert is False
    assert service._active_anomaly is None
    pi_client.notify_status.assert_called_with(
        status="NORMAL",
        event_type="NORMAL",
        face_count=1,
        explanation="Normal candidate presence restored.",
    )

    # Candidate disappears again at T=10.0
    service._update_temporal_state(face_count=0, frame=frame, now_mono=10.0)
    # Reaches new threshold at T=15.2 (15.2 - 10.0 = 5.2s >= 5.0s)
    status, is_alert = service._update_temporal_state(face_count=0, frame=frame, now_mono=15.2)
    assert is_alert is True
    assert len(logger_svc.get_recent_events()) == 2, "Second separate absence event was not recorded!"


def test_multiple_faces_threshold_and_reset(mock_monitoring):
    """Multiple faces trigger alert after 2.0s, and reset when returning to 1 face."""
    service, logger_svc, pi_client = mock_monitoring
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    # T=0.0: 2 faces appear
    status, is_alert = service._update_temporal_state(face_count=2, frame=frame, now_mono=0.0)
    assert "WARNING" in status
    assert is_alert is False

    # T=1.5: 2 faces persist but < 2.0s threshold
    status, is_alert = service._update_temporal_state(face_count=2, frame=frame, now_mono=1.5)
    assert is_alert is False
    assert len(logger_svc.get_recent_events()) == 0

    # T=2.2: >= 2.0s threshold -> Alert triggered
    status, is_alert = service._update_temporal_state(face_count=2, frame=frame, now_mono=2.2)
    assert is_alert is True
    assert "ALERT: 2 FACES DETECTED" in status

    events = logger_svc.get_recent_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "MULTIPLE_FACES"
    assert events[0]["face_count"] == 2

    # Return to 1 face at T=3.0 -> Clears multiple anomaly
    status, is_alert = service._update_temporal_state(face_count=1, frame=frame, now_mono=3.0)
    assert status == "NORMAL"
    assert is_alert is False
    assert service._active_anomaly is None


def test_camera_failure_handling(mock_monitoring):
    """Camera failure >= 3.0s triggers CAMERA_ERROR event."""
    service, logger_svc, pi_client = mock_monitoring

    # T=0.0: Failure starts
    service._handle_camera_failure(now_mono=0.0)
    assert len(logger_svc.get_recent_events()) == 0

    # T=3.1: >= 3.0s threshold -> Triggers camera error
    service._handle_camera_failure(now_mono=3.1)
    events = logger_svc.get_recent_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "CAMERA_ERROR"
    assert events[0]["is_camera_fault"] is True
