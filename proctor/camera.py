"""Camera management module for macOS webcam capture.

Handles thread-safe frame acquisition using cv2.CAP_AVFOUNDATION, ensures
a single camera handle is shared across background proctoring and Flask MJPEG
streaming, and provides actionable macOS permission diagnostics.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CameraStatus:
    is_open: bool
    camera_index: int
    backend: str
    width: int
    height: int
    fps: int
    error_message: Optional[str] = None


class CameraManager:
    """Singleton-friendly, thread-safe camera capture manager.

    Maintains a single VideoCapture instance running in a dedicated thread to
    prevent resource contention and excessive buffering on macOS AVFoundation.
    """

    _instance: Optional["CameraManager"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        camera_index: int = 0,
        backend_name: str = "AVFOUNDATION",
        width: int = 640,
        height: int = 480,
        fps: int = 15,
        synthetic: bool = False,
    ) -> None:
        self.camera_index = camera_index
        self.backend_name = backend_name
        self.width = width
        self.height = height
        self.fps = fps
        self.synthetic = synthetic

        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._last_read_time = 0.0
        self._consecutive_failures = 0
        self._error_message: Optional[str] = None

    @classmethod
    def get_instance(cls, **kwargs) -> "CameraManager":
        """Retrieve or create the shared CameraManager singleton."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(**kwargs)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Release and reset the shared CameraManager singleton (used for tests/shutdown)."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.stop()
                cls._instance = None

    def _resolve_backend(self) -> int:
        """Resolve backend flag based on OS and configuration."""
        if self.backend_name == "AVFOUNDATION" and sys.platform == "darwin":
            return cv2.CAP_AVFOUNDATION
        return cv2.CAP_ANY

    def start(self) -> bool:
        """Open the camera and start the background frame capture loop."""
        with self._frame_lock:
            if self._running:
                return True

            if self.synthetic:
                self._running = True
                self._error_message = None
                self._thread = threading.Thread(target=self._synthetic_loop, daemon=True)
                self._thread.start()
                logger.info("Started synthetic camera mode.")
                return True

            backend = self._resolve_backend()
            logger.info(
                f"Opening camera index {self.camera_index} with backend {self.backend_name}..."
            )
            try:
                self._cap = cv2.VideoCapture(self.camera_index, backend)
            except Exception as e:
                self._error_message = f"Exception opening camera: {e}"
                logger.error(self._error_message)
                return False

            if not self._cap.isOpened():
                diag = (
                    "Could not open camera. Possible causes:\n"
                    "1. macOS Camera permission denied. Grant camera access to Terminal/IDE in:\n"
                    "   System Settings > Privacy & Security > Camera.\n"
                    "2. External USB webcam disconnected or in use by another application.\n"
                    f"3. Invalid camera index (currently requested: {self.camera_index})."
                )
                self._error_message = diag
                logger.error(diag)
                self._cap = None
                return False

            # Configure resolution and target frame rate for smooth low-CPU capture
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)

            # Read actual configured properties
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = int(self._cap.get(cv2.CAP_PROP_FPS))
            logger.info(
                f"Camera opened successfully. Resolution: {actual_w}x{actual_h}, FPS: {actual_fps}"
            )

            self._running = True
            self._error_message = None
            self._consecutive_failures = 0
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            return True

    def _capture_loop(self) -> None:
        """Background thread reading frames at the configured target FPS."""
        frame_interval = 1.0 / max(1, self.fps)

        while self._running and self._cap is not None:
            loop_start = time.monotonic()

            success, frame = self._cap.read()
            if not success or frame is None:
                self._consecutive_failures += 1
                if self._consecutive_failures % 30 == 1:
                    logger.warning(
                        f"Failed frame read from camera (failures: {self._consecutive_failures})."
                    )
                time.sleep(0.05)
                continue

            self._consecutive_failures = 0
            with self._frame_lock:
                self._latest_frame = frame
                self._last_read_time = time.monotonic()

            elapsed = time.monotonic() - loop_start
            sleep_time = max(0.001, frame_interval - elapsed)
            time.sleep(sleep_time)

    def _synthetic_loop(self) -> None:
        """Generate synthetic test frames for automated testing or headless environments."""
        frame_interval = 1.0 / max(1, self.fps)
        while self._running:
            loop_start = time.monotonic()
            # Create a 640x480 frame with dark gray background and timestamp
            frame = np.full((self.height, self.width, 3), 40, dtype=np.uint8)
            t_str = time.strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(
                frame,
                f"SYNTHETIC CAMERA FEED - {t_str}",
                (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )
            with self._frame_lock:
                self._latest_frame = frame
                self._last_read_time = time.monotonic()

            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.001, frame_interval - elapsed))

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Retrieve the latest captured frame safely."""
        with self._frame_lock:
            if not self._running or self._latest_frame is None:
                return False, None
            # Return a copy to avoid threading race conditions during downstream processing
            return True, self._latest_frame.copy()

    def get_status(self) -> CameraStatus:
        """Return diagnostic camera status."""
        with self._frame_lock:
            is_open = self._running and (self._cap is not None or self.synthetic)
            return CameraStatus(
                is_open=is_open,
                camera_index=self.camera_index,
                backend=self.backend_name,
                width=self.width,
                height=self.height,
                fps=self.fps,
                error_message=self._error_message,
            )

    def stop(self) -> None:
        """Cleanly stop background thread and release hardware camera."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

        with self._frame_lock:
            if self._cap is not None:
                logger.info("Releasing camera handle...")
                self._cap.release()
                self._cap = None
            self._latest_frame = None
            logger.info("Camera stopped cleanly.")
