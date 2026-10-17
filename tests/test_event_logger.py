"""Tests for SQLite EventLogger and snapshot handling."""

from datetime import datetime
import numpy as np
import pytest

from proctor.event_logger import EventLogger


@pytest.fixture
def temp_logger(tmp_path):
    db_file = tmp_path / "test_proctoring.db"
    evidence_dir = tmp_path / "evidence"
    return EventLogger(db_path=db_file, evidence_dir=evidence_dir)


def test_event_creation_and_retrieval(temp_logger):
    """Test creating an event with ISO 8601 timestamp and retrieving it."""
    synthetic_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    event = temp_logger.log_event(
        event_type="FACE_ABSENT",
        face_count=0,
        explanation="Candidate absent from frame",
        session_id="test_session_1",
        frame=synthetic_frame,
    )

    assert event.id.startswith("EVT-")
    assert event.event_type == "FACE_ABSENT"
    assert event.face_count == 0
    assert event.snapshot_filename is not None

    # Validate ISO 8601 format with timezone
    parsed_time = datetime.fromisoformat(event.timestamp)
    assert parsed_time.tzinfo is not None

    # Verify retrieval
    events = temp_logger.get_recent_events(session_id="test_session_1")
    assert len(events) == 1
    assert events[0]["id"] == event.id
    assert events[0]["snapshot_filename"] == event.snapshot_filename


def test_event_counts_aggregation(temp_logger):
    """Test aggregating event counts by anomaly type."""
    temp_logger.log_event("FACE_ABSENT", 0, "Absence 1", session_id="s1")
    temp_logger.log_event("FACE_ABSENT", 0, "Absence 2", session_id="s1")
    temp_logger.log_event("MULTIPLE_FACES", 2, "Two faces", session_id="s1")
    temp_logger.log_event("CAMERA_ERROR", 0, "Camera lost", session_id="s1", is_camera_fault=True)

    counts = temp_logger.get_event_counts(session_id="s1")
    assert counts["FACE_ABSENT"] == 2
    assert counts["MULTIPLE_FACES"] == 1
    assert counts["CAMERA_ERROR"] == 1
    assert counts["TOTAL_ANOMALIES"] == 3


def test_clear_events(temp_logger):
    """Test clearing events from DB and deleting snapshot files."""
    frame = np.ones((50, 50, 3), dtype=np.uint8) * 128
    event = temp_logger.log_event("FACE_ABSENT", 0, "Test", frame=frame)
    snapshot_path = temp_logger.evidence_dir / event.snapshot_filename
    assert snapshot_path.exists()

    deleted = temp_logger.clear_events()
    assert deleted == 1
    assert len(temp_logger.get_recent_events()) == 0
    assert not snapshot_path.exists()


def test_snapshot_write_failure_resilience(temp_logger):
    """Test logger resilience when frame is None or empty."""
    event = temp_logger.log_event(
        event_type="FACE_ABSENT",
        face_count=0,
        explanation="No frame provided",
        frame=None,
    )
    assert event.id.startswith("EVT-")
    assert event.snapshot_filename is None
