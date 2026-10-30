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
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CameraStatus:
    is_open: bool
    camera_index: int
    camera_label: str
    backend: str
    width: int
    height: int
    fps: int
    error_message: Optional[str] = None


class CameraManager:
    """Singleton-friendly, thread-safe camera capture manager.

    Maintains a single VideoCapture instance running in a dedicated thread to
    prevent resource contention and excessive buffering on macOS AVFoundation.
    Supports auto-detecting native laptop camera or external USB webcams.
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
        auto_detect: bool = True,
        camera_source: str = "auto",
    ) -> None:
        self.camera_index = camera_index
        self.backend_name = backend_name
        self.width = width
        self.height = height
        self.fps = fps
        self.synthetic = synthetic
        self.auto_detect = auto_detect
        self.camera_source = str(camera_source).strip().lower()
        self.camera_label = (
            "Native Laptop Camera" if camera_index == 0 else f"External USB Webcam (Index {camera_index})"
        )

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

    @classmethod
    def scan_available_cameras(cls, backend_name: str = "AVFOUNDATION", max_probe: int = 3) -> List[Dict[str, Any]]:
        """Probe connected camera devices and return descriptive metadata."""
        cameras: List[Dict[str, Any]] = []
        backend = cv2.CAP_AVFOUNDATION if (backend_name == "AVFOUNDATION" and sys.platform == "darwin") else cv2.CAP_ANY

        for idx in range(max_probe):
            try:
                cap = cv2.VideoCapture(idx, backend)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        label = "Native Laptop Camera" if idx == 0 else f"External USB Webcam (Index {idx})"
                        cameras.append({
                            "index": idx,
                            "label": label,
                            "is_native": idx == 0,
                            "is_external": idx > 0,
                            "width": w,
                            "height": h,
                            "available": True,
                        })
                    cap.release()
            except Exception as e:
                logger.debug(f"Camera index {idx} scan error: {e}")
        return cameras

    def get_available_cameras(self) -> List[Dict[str, Any]]:
        """List available cameras with indicator for the active camera."""
        if self.synthetic:
            return [{
                "index": -1,
                "label": "Synthetic Test Camera",
                "is_native": False,
                "is_external": False,
                "width": self.width,
                "height": self.height,
                "available": True,
                "active": True,
            }]

        cameras = self.scan_available_cameras(self.backend_name)
        for cam in cameras:
            cam["active"] = (cam["index"] == self.camera_index and self._running)
        return cameras

    def switch_camera(self, new_index: int) -> bool:
        """Switch camera device at runtime without restarting the application."""
        with self._instance_lock:
            logger.info(f"Switching active camera to index {new_index}...")
            self.stop()
            self.camera_index = new_index
            self.camera_source = str(new_index)
            self.camera_label = (
                "Native Laptop Camera" if new_index == 0 else f"External USB Webcam (Index {new_index})"
            )
            return self.start()

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

            # Determine probing order based on camera_source
            indices_to_try: List[int] = []
            if self.camera_source == "external":
                logger.info("External camera requested. Probing external camera indices [1, 2] first...")
                indices_to_try = [1, 2]
                if self.auto_detect:
                    indices_to_try.append(0)  # Graceful fallback to native if external missing
            elif self.camera_source == "native":
                logger.info("Native laptop camera requested. Probing index 0...")
                indices_to_try = [0]
                if self.auto_detect:
                    indices_to_try.extend([1, 2])
            elif self.camera_source.isdigit():
                indices_to_try = [int(self.camera_source)]
                if self.auto_detect:
                    for alt in [0, 1, 2]:
                        if alt not in indices_to_try:
                            indices_to_try.append(alt)
            else:  # "auto" or default
                indices_to_try = [self.camera_index]
                if self.auto_detect:
                    for alt in [0, 1, 2]:
                        if alt not in indices_to_try:
                            indices_to_try.append(alt)

            opened_cap = None
            for idx in indices_to_try:
                try:
                    test_cap = cv2.VideoCapture(idx, backend)
                    if test_cap.isOpened():
                        # Set capture properties
                        test_cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                        test_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                        test_cap.set(cv2.CAP_PROP_FPS, self.fps)
                        success, frame = test_cap.read()
                        if success and frame is not None:
                            opened_cap = test_cap
                            self.camera_index = idx
                            self.camera_label = (
                                "Native Laptop Camera"
                                if idx == 0
                                else f"External USB Webcam (Index {idx})"
                            )
                            logger.info(
                                f"Successfully opened {self.camera_label} on index {idx}."
                            )
                            break
                        else:
                            test_cap.release()
                    else:
                        test_cap.release()
                except Exception as e:
                    logger.debug(f"Camera index {idx} probe error: {e}")

            if opened_cap is None:
                diag = (
                    "Could not open camera. Possible causes:\n"
                    "1. macOS Camera permission denied. Grant camera access to Terminal/IDE in:\n"
                    "   System Settings > Privacy & Security > Camera.\n"
                    "2. External USB webcam disconnected or in use by another application.\n"
                    f"3. Probed indices {indices_to_try} all failed to provide frames."
                )
                self._error_message = diag
                logger.error(diag)
                self._cap = None
                return False

            self._cap = opened_cap
            # Read actual configured properties
            actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = int(self._cap.get(cv2.CAP_PROP_FPS))
            logger.info(
                f"{self.camera_label} active. Resolution: {actual_w}x{actual_h}, FPS: {actual_fps}"
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
                camera_label=self.camera_label,
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
