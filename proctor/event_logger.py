"""Event logging and evidence capture module.

Persists proctoring anomalies to a local SQLite database, stores keyed JPEG
snapshots in the evidence/ folder, enforces ISO 8601 timestamps with timezone,
and isolates file I/O to guarantee core monitoring resilience.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ProctorEvent:
    id: str
    session_id: str
    timestamp: str
    event_type: str
    face_count: int
    explanation: str
    snapshot_filename: Optional[str] = None
    is_camera_fault: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "face_count": self.face_count,
            "explanation": self.explanation,
            "snapshot_filename": self.snapshot_filename,
            "is_camera_fault": self.is_camera_fault,
        }


class EventLogger:
    """Thread-safe SQLite event logger and evidence snapshot manager."""

    def __init__(self, db_path: Path, evidence_dir: Path) -> None:
        self.db_path = Path(db_path)
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with row factory enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create database tables if they do not exist."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    face_count INTEGER NOT NULL,
                    explanation TEXT NOT NULL,
                    snapshot_filename TEXT,
                    is_camera_fault INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp)
                """
            )
            conn.commit()
        logger.info(f"Initialized event database at {self.db_path}")

    def save_snapshot(self, event_id: str, frame: np.ndarray) -> Optional[str]:
        """Save a frame snapshot to disk. Handles I/O errors gracefully."""
        if frame is None or frame.size == 0:
            return None

        filename = f"{event_id}.jpg"
        target_path = self.evidence_dir / filename

        try:
            # Save compressed JPEG snapshot (quality 85)
            success = cv2.imwrite(
                str(target_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            )
            if success:
                logger.info(f"Saved evidence snapshot to {target_path}")
                return filename
            logger.warning(f"Failed to encode/write snapshot to {target_path}")
            return None
        except Exception as e:
            logger.error(f"Error saving snapshot for event {event_id}: {e}")
            return None

    def log_event(
        self,
        event_type: str,
        face_count: int,
        explanation: str,
        session_id: str = "default_session",
        frame: Optional[np.ndarray] = None,
        is_camera_fault: bool = False,
    ) -> ProctorEvent:
        """Create and store a proctoring or hardware diagnostic event."""
        # Use timezone-aware local ISO 8601 string
        now = datetime.now(timezone.utc).astimezone()
        timestamp_str = now.isoformat()
        unique_suffix = uuid.uuid4().hex[:8]
        event_id = f"EVT-{now.strftime('%Y%m%d-%H%M%S')}-{unique_suffix}"

        snapshot_filename = None
        if frame is not None and not is_camera_fault:
            snapshot_filename = self.save_snapshot(event_id, frame)

        event = ProctorEvent(
            id=event_id,
            session_id=session_id,
            timestamp=timestamp_str,
            event_type=event_type,
            face_count=face_count,
            explanation=explanation,
            snapshot_filename=snapshot_filename,
            is_camera_fault=is_camera_fault,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    id, session_id, timestamp, event_type, face_count,
                    explanation, snapshot_filename, is_camera_fault, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.session_id,
                    event.timestamp,
                    event.event_type,
                    event.face_count,
                    event.explanation,
                    event.snapshot_filename,
                    1 if event.is_camera_fault else 0,
                    now.timestamp(),
                ),
            )
            conn.commit()

        logger.info(f"Logged event [{event.event_type}] ID={event.id}: {explanation}")
        return event

    def get_recent_events(
        self, limit: int = 50, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve recent events ordered by timestamp descending."""
        query = "SELECT * FROM events"
        params: List[Any] = []
        if session_id:
            query += " WHERE session_id = ?"
            params.append(session_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        events = []
        for r in rows:
            events.append(
                {
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "timestamp": r["timestamp"],
                    "event_type": r["event_type"],
                    "face_count": r["face_count"],
                    "explanation": r["explanation"],
                    "snapshot_filename": r["snapshot_filename"],
                    "is_camera_fault": bool(r["is_camera_fault"]),
                }
            )
        return events

    def get_event_counts(self, session_id: Optional[str] = None) -> Dict[str, int]:
        """Aggregate event counts by type for live dashboard telemetry."""
        query = "SELECT event_type, COUNT(*) as cnt FROM events"
        params: List[Any] = []
        if session_id:
            query += " WHERE session_id = ?"
            params.append(session_id)
        query += " GROUP BY event_type"

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        counts = {
            "FACE_ABSENT": 0,
            "MULTIPLE_FACES": 0,
            "CAMERA_ERROR": 0,
            "TOTAL_ANOMALIES": 0,
        }
        for r in rows:
            etype = r["event_type"]
            cnt = r["cnt"]
            counts[etype] = cnt
            if etype in ("FACE_ABSENT", "MULTIPLE_FACES"):
                counts["TOTAL_ANOMALIES"] += cnt

        return counts

    def clear_events(self, session_id: Optional[str] = None) -> int:
        """Clear test events from the database and optionally unlink evidence snapshots."""
        query = "SELECT snapshot_filename FROM events"
        params: List[Any] = []
        if session_id:
            query += " WHERE session_id = ?"
            params.append(session_id)

        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            for r in rows:
                fname = r["snapshot_filename"]
                if fname:
                    file_path = self.evidence_dir / fname
                    if file_path.exists():
                        try:
                            file_path.unlink()
                        except Exception as e:
                            logger.warning(f"Could not remove snapshot {file_path}: {e}")

            del_query = "DELETE FROM events"
            del_params: List[Any] = []
            if session_id:
                del_query += " WHERE session_id = ?"
                del_params.append(session_id)
            cursor = conn.execute(del_query, del_params)
            deleted_count = cursor.rowcount
            conn.commit()

        logger.info(f"Cleared {deleted_count} events from database.")
        return deleted_count
