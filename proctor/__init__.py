"""Exam Proctoring System - Core Proctoring Package."""

from proctor.camera import CameraManager, CameraStatus
from proctor.face_detector import FaceDetector, DetectedFace
from proctor.event_logger import EventLogger, ProctorEvent
from proctor.pi_client import RaspberryPiClient
from proctor.monitoring import MonitoringService, MonitoringStatus

__all__ = [
    "CameraManager",
    "CameraStatus",
    "FaceDetector",
    "DetectedFace",
    "EventLogger",
    "ProctorEvent",
    "RaspberryPiClient",
    "MonitoringService",
    "MonitoringStatus",
]
