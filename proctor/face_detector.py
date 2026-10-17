"""Face detection and annotation module using OpenCV Haar Cascades.

Preserves the tested, reliable Haar Cascade detector as the baseline for
low-latency CPU evaluation on MacBook Intel architecture without introducing
heavy dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class DetectedFace:
    x: int
    y: int
    w: int
    h: int

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


class FaceDetector:
    """Haar Cascade face detector."""

    def __init__(
        self,
        cascade_filename: str = "haarcascade_frontalface_default.xml",
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: Tuple[int, int] = (50, 50),
    ) -> None:
        self.scale_factor = scale_factor
        self.min_neighbors = min_neighbors
        self.min_size = min_size

        cascade_path = cv2.data.haarcascades + cascade_filename
        self.classifier = cv2.CascadeClassifier(cascade_path)

        if self.classifier.empty():
            msg = f"Failed to load Haar cascade classifier from {cascade_path}"
            logger.error(msg)
            raise RuntimeError(msg)

        logger.info(f"Loaded face detector cascade from {cascade_path}")

    def detect(self, frame: np.ndarray) -> List[DetectedFace]:
        """Detect faces in a BGR frame. Returns list of DetectedFace objects."""
        if frame is None or frame.size == 0:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Apply histogram equalization for varying ambient lighting
        gray = cv2.equalizeHist(gray)

        rects = self.classifier.detectMultiScale(
            gray,
            scaleFactor=self.scale_factor,
            minNeighbors=self.min_neighbors,
            minSize=self.min_size,
        )

        faces = [DetectedFace(int(x), int(y), int(w), int(h)) for (x, y, w, h) in rects]
        return faces

    def annotate(
        self,
        frame: np.ndarray,
        faces: List[DetectedFace],
        status_text: str = "NORMAL",
        alert_active: bool = False,
        elapsed_sec: Optional[float] = None,
    ) -> np.ndarray:
        """Draw bounding boxes, status banner, and diagnostic telemetry on the frame."""
        annotated = frame.copy()
        face_count = len(faces)

        # Draw bounding boxes for detected faces
        # Green for single face, Amber/Red for multiple faces
        box_color = (0, 255, 0) if face_count == 1 else (0, 140, 255)
        for idx, face in enumerate(faces):
            cv2.rectangle(
                annotated,
                (face.x, face.y),
                (face.x + face.w, face.y + face.h),
                box_color,
                2,
            )
            cv2.putText(
                annotated,
                f"Candidate #{idx + 1}",
                (face.x, max(20, face.y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                box_color,
                1,
                cv2.LINE_AA,
            )

        # Overlay top telemetry HUD bar
        hud_bg_color = (30, 30, 30)
        cv2.rectangle(annotated, (0, 0), (annotated.shape[1], 44), hud_bg_color, -1)

        # Status text color
        if alert_active:
            status_color = (0, 0, 255)  # Red for active alert
        elif status_text == "NORMAL":
            status_color = (0, 255, 0)  # Green for normal
        else:
            status_color = (0, 200, 255)  # Yellow for warning/transitioning

        hud_label = f"STATUS: {status_text} | FACES: {face_count}"
        if elapsed_sec is not None:
            mins, secs = divmod(int(elapsed_sec), 60)
            hud_label += f" | TIME: {mins:02d}:{secs:02d}"

        cv2.putText(
            annotated,
            hud_label,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            status_color,
            2,
            cv2.LINE_AA,
        )

        return annotated
