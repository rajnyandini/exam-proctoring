"""Tests for Haar Cascade FaceDetector and HUD frame annotation."""

import numpy as np
import pytest

from proctor.face_detector import DetectedFace, FaceDetector


def test_face_detector_initialization():
    """Verify face detector loads OpenCV default Haar cascade without error."""
    detector = FaceDetector()
    assert detector.classifier is not None
    assert not detector.classifier.empty()


def test_detect_on_blank_frame():
    """Verify detector handles blank/uniform images without errors."""
    detector = FaceDetector()
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    faces = detector.detect(blank_frame)
    assert isinstance(faces, list)
    assert len(faces) == 0


def test_annotate_frame():
    """Verify frame annotation draws bounding boxes and status banner."""
    detector = FaceDetector()
    test_frame = np.full((480, 640, 3), 100, dtype=np.uint8)
    dummy_faces = [DetectedFace(x=50, y=50, w=100, h=100)]

    annotated = detector.annotate(
        frame=test_frame,
        faces=dummy_faces,
        status_text="NORMAL",
        alert_active=False,
        elapsed_sec=42.5,
    )

    assert annotated.shape == test_frame.shape
    # Frame should have been modified (HUD rectangle and bounding box drawn)
    assert not np.array_equal(test_frame, annotated)
