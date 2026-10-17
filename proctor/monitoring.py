"""Core proctoring state machine and monitoring coordinator.

Tracks candidate presence, manages monotonic duration timers for threshold logic,
suppresses duplicate alerts during persistent conditions, coordinates evidence capture,
and publishes real-time annotated frames to the dashboard.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from proctor.camera import CameraManager
from proctor.face_detector import DetectedFace, FaceDetector
from proctor.event_logger import EventLogger, ProctorEvent
from proctor.pi_client import RaspberryPiClient

logger = logging.getLogger(__name__)


@dataclass
class MonitoringStatus:
    is_active: bool
    session_id: str
    session_start_time: Optional[float]
    elapsed_seconds: float
    current_status: str  # NORMAL, FACE_ABSENT, MULTIPLE_FACES, CAMERA_ERROR, STOPPED
    face_count: int
    active_anomaly: Optional[str]
    absence_elapsed_sec: float
    multiple_elapsed_sec: float
    camera_online: bool
    pi_online: bool
    event_counts: Dict[str, int]


class MonitoringService:
    """Thread-safe proctoring session manager and real-time state machine."""

    def __init__(
        self,
        camera: CameraManager,
        detector: FaceDetector,
        logger_service: EventLogger,
        pi_client: RaspberryPiClient,
        face_absence_threshold_sec: float = 5.0,
        multiple_faces_threshold_sec: float = 2.0,
        camera_error_threshold_sec: float = 3.0,
    ) -> None:
        self.camera = camera
        self.detector = detector
        self.logger_service = logger_service
        self.pi_client = pi_client

        self.face_absence_threshold_sec = face_absence_threshold_sec
        self.multiple_faces_threshold_sec = multiple_faces_threshold_sec
        self.camera_error_threshold_sec = camera_error_threshold_sec

        self._lock = threading.Lock()
        self._is_running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Session tracking
        self.session_id = "proctor_session_0"
        self._session_start_monotonic: Optional[float] = None
        self._session_start_wall: Optional[float] = None

        # State machine variables (using monotonic clocks)
        self._current_face_count = 0
        self._detected_faces: List[DetectedFace] = []
        self._absence_start_mono: Optional[float] = None
        self._multiple_start_mono: Optional[float] = None
        self._camera_fail_start_mono: Optional[float] = None

        # Continuous anomaly state suppression
        self._active_anomaly: Optional[str] = None
        self._current_status = "STOPPED"

        # Frame distribution for MJPEG stream
        self._annotated_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()

    def start_session(self, session_id: Optional[str] = None) -> str:
        """Start a new proctoring session and launch worker thread."""
        with self._lock:
            if self._is_running:
                logger.info(f"Session already running with ID {self.session_id}")
                return self.session_id

            # Start camera hardware if not already running
            if not self.camera.start():
                logger.warning("Camera failed to start during session initialization.")

            if not session_id:
                if not hasattr(self, "_session_counter"):
                    self._session_counter = 0
                self._session_counter += 1
                self.session_id = f"Session {self._session_counter}"
            else:
                self.session_id = session_id

            self._session_start_monotonic = time.monotonic()
            self._session_start_wall = time.time()
            self._absence_start_mono = None
            self._multiple_start_mono = None
            self._camera_fail_start_mono = None
            self._active_anomaly = None
            self._current_status = "NORMAL"
            self._is_running = True

            self._worker_thread = threading.Thread(
                target=self._evaluation_loop, daemon=True
            )
            self._worker_thread.start()

            logger.info(f"Proctoring session '{self.session_id}' started.")
            # Notify Pi of session start in normal state
            self.pi_client.notify_status(
                status="NORMAL",
                event_type="NORMAL",
                face_count=1,
                explanation=f"Session {self.session_id} started.",
            )
            return self.session_id

    def stop_session(self) -> None:
        """Stop the active session and cleanly terminate worker thread."""
        with self._lock:
            if not self._is_running:
                return

            self._is_running = False
            self._current_status = "STOPPED"

        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)
            self._worker_thread = None

        # Notify Pi that session ended
        self.pi_client.notify_status(
            status="NORMAL",
            event_type="NORMAL",
            face_count=0,
            explanation=f"Session {self.session_id} ended.",
        )
        logger.info(f"Proctoring session '{self.session_id}' stopped.")

    def _evaluation_loop(self) -> None:
        """Continuous frame processing and temporal state evaluation loop."""
        while self._is_running:
            loop_start = time.monotonic()

            success, frame = self.camera.read()
            now_mono = time.monotonic()

            if not success or frame is None:
                self._handle_camera_failure(now_mono)
                time.sleep(0.05)
                continue

            # Clear camera failure timer upon successful frame capture
            self._camera_fail_start_mono = None

            # Detect faces using baseline Haar cascade
            faces = self.detector.detect(frame)
            face_count = len(faces)

            # Evaluate temporal threshold logic
            status_text, is_alert = self._update_temporal_state(
                face_count=face_count,
                frame=frame,
                now_mono=now_mono,
            )

            # Generate annotated HUD frame for live stream
            elapsed = (
                now_mono - self._session_start_monotonic
                if self._session_start_monotonic
                else 0.0
            )
            annotated = self.detector.annotate(
                frame=frame,
                faces=faces,
                status_text=status_text,
                alert_active=is_alert,
                elapsed_sec=elapsed,
            )

            with self._frame_lock:
                self._annotated_frame = annotated
                self._current_face_count = face_count
                self._detected_faces = faces

            # Sleep to pace loop near camera frame rate
            loop_elapsed = time.monotonic() - loop_start
            target_interval = 1.0 / max(1, self.camera.fps)
            time.sleep(max(0.005, target_interval - loop_elapsed))

    def _handle_camera_failure(self, now_mono: float) -> None:
        """Track continuous camera failure duration and flag error if threshold exceeded."""
        if self._camera_fail_start_mono is None:
            self._camera_fail_start_mono = now_mono

        fail_duration = now_mono - self._camera_fail_start_mono
        if fail_duration >= self.camera_error_threshold_sec:
            if self._active_anomaly != "CAMERA_ERROR":
                self._active_anomaly = "CAMERA_ERROR"
                self._current_status = "CAMERA ERROR"
                self.logger_service.log_event(
                    event_type="CAMERA_ERROR",
                    face_count=0,
                    explanation=(
                        f"Webcam stream interrupted for {fail_duration:.1f}s. "
                        "Check USB connection or macOS permissions."
                    ),
                    session_id=self.session_id,
                    frame=None,
                    is_camera_fault=True,
                )
                self.pi_client.notify_status(
                    status="ALERT",
                    event_type="CAMERA_ERROR",
                    face_count=0,
                    explanation="Camera stream lost.",
                )

    def _update_temporal_state(
        self,
        face_count: int,
        frame: np.ndarray,
        now_mono: float,
    ) -> Tuple[str, bool]:
        """Update temporal state machines with monotonic duration thresholds.

        Returns (status_label, is_alert_active).
        """
        # --- Case 1: Exactly 1 face (Normal condition) ---
        if face_count == 1:
            # Reset absence and multiple timers immediately
            self._absence_start_mono = None
            self._multiple_start_mono = None

            # If an anomaly was previously active, clear it and notify Pi
            if self._active_anomaly is not None:
                logger.info(
                    f"Anomaly condition '{self._active_anomaly}' resolved. Normal proctoring restored."
                )
                self._active_anomaly = None
                self.pi_client.notify_status(
                    status="NORMAL",
                    event_type="NORMAL",
                    face_count=1,
                    explanation="Normal candidate presence restored.",
                )

            self._current_status = "NORMAL"
            return "NORMAL", False

        # --- Case 2: 0 faces (Potential Face Absence) ---
        elif face_count == 0:
            self._multiple_start_mono = None

            if self._absence_start_mono is None:
                self._absence_start_mono = now_mono

            elapsed_absence = now_mono - self._absence_start_mono

            if elapsed_absence >= self.face_absence_threshold_sec:
                # Persistent absence reached threshold
                if self._active_anomaly != "FACE_ABSENT":
                    self._active_anomaly = "FACE_ABSENT"
                    explanation = (
                        f"No face detected in video frame for {elapsed_absence:.1f} seconds "
                        f"(Threshold: {self.face_absence_threshold_sec:.1f}s). Requires human review."
                    )
                    self.logger_service.log_event(
                        event_type="FACE_ABSENT",
                        face_count=0,
                        explanation=explanation,
                        session_id=self.session_id,
                        frame=frame,
                    )
                    self.pi_client.notify_status(
                        status="ALERT",
                        event_type="FACE_ABSENT",
                        face_count=0,
                        explanation=explanation,
                    )

                self._current_status = "FACE ABSENT"
                return "ALERT: FACE ABSENT", True
            else:
                # Transitioning / momentary absence below threshold
                rem = max(0.0, self.face_absence_threshold_sec - elapsed_absence)
                self._current_status = f"WARNING: NO FACE ({rem:.1f}s)"
                return f"WARNING: NO FACE ({rem:.1f}s)", False

        # --- Case 3: 2 or more faces (Potential Multiple Faces) ---
        else:  # face_count >= 2
            self._absence_start_mono = None

            if self._multiple_start_mono is None:
                self._multiple_start_mono = now_mono

            elapsed_multiple = now_mono - self._multiple_start_mono

            if elapsed_multiple >= self.multiple_faces_threshold_sec:
                # Persistent multiple faces reached threshold
                if self._active_anomaly != "MULTIPLE_FACES":
                    self._active_anomaly = "MULTIPLE_FACES"
                    explanation = (
                        f"Detected {face_count} faces simultaneously for {elapsed_multiple:.1f} seconds "
                        f"(Threshold: {self.multiple_faces_threshold_sec:.1f}s). Requires human review."
                    )
                    self.logger_service.log_event(
                        event_type="MULTIPLE_FACES",
                        face_count=face_count,
                        explanation=explanation,
                        session_id=self.session_id,
                        frame=frame,
                    )
                    self.pi_client.notify_status(
                        status="ALERT",
                        event_type="MULTIPLE_FACES",
                        face_count=face_count,
                        explanation=explanation,
                    )

                self._current_status = "MULTIPLE FACES"
                return f"ALERT: {face_count} FACES DETECTED", True
            else:
                rem = max(0.0, self.multiple_faces_threshold_sec - elapsed_multiple)
                self._current_status = f"WARNING: {face_count} FACES ({rem:.1f}s)"
                return f"WARNING: {face_count} FACES ({rem:.1f}s)", False

    def get_annotated_frame(self) -> Optional[np.ndarray]:
        """Retrieve the latest annotated HUD frame for MJPEG encoding."""
        with self._frame_lock:
            if self._annotated_frame is not None:
                return self._annotated_frame.copy()
        # Fallback to direct camera frame if unannotated
        success, frame = self.camera.read()
        return frame if success else None

    def get_telemetry(self) -> MonitoringStatus:
        """Produce comprehensive real-time telemetry snapshot for dashboard polling."""
        with self._lock:
            is_active = self._is_running
            now_mono = time.monotonic()
            elapsed_sec = (
                now_mono - self._session_start_monotonic
                if (is_active and self._session_start_monotonic is not None)
                else 0.0
            )

            absence_elapsed = (
                now_mono - self._absence_start_mono
                if self._absence_start_mono is not None
                else 0.0
            )
            multiple_elapsed = (
                now_mono - self._multiple_start_mono
                if self._multiple_start_mono is not None
                else 0.0
            )

            cam_status = self.camera.get_status()
            pi_status = self.pi_client.get_status()
            counts = self.logger_service.get_event_counts(self.session_id)

            return MonitoringStatus(
                is_active=is_active,
                session_id=self.session_id,
                session_start_time=self._session_start_wall,
                elapsed_seconds=elapsed_sec,
                current_status=self._current_status,
                face_count=self._current_face_count,
                active_anomaly=self._active_anomaly,
                absence_elapsed_sec=absence_elapsed,
                multiple_elapsed_sec=multiple_elapsed,
                camera_online=cam_status.is_open,
                pi_online=pi_status.online,
                event_counts=counts,
            )
