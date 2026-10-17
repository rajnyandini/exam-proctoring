"""Configuration module for the Exam Proctoring System.

Loads environment variables from .env file if present, providing typed,
centralized settings with safe defaults for MacBook and Raspberry Pi integration.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root directory
BASE_DIR = Path(__file__).resolve().parent

# Load .env if present
load_dotenv(BASE_DIR / ".env")


class Config:
    """Central configuration class."""

    # Base directories
    BASE_DIR: Path = BASE_DIR
    EVIDENCE_DIR: Path = BASE_DIR / os.getenv("EVIDENCE_DIR", "evidence")
    DATA_DIR: Path = BASE_DIR / os.getenv("DATA_DIR", "data")
    DB_PATH: Path = BASE_DIR / os.getenv("DB_PATH", "data/proctoring.db")

    # Camera settings
    CAMERA_INDEX: int = int(os.getenv("CAMERA_INDEX", "0"))
    CAMERA_BACKEND: str = os.getenv("CAMERA_BACKEND", "AVFOUNDATION").upper()
    FRAME_WIDTH: int = int(os.getenv("FRAME_WIDTH", "640"))
    FRAME_HEIGHT: int = int(os.getenv("FRAME_HEIGHT", "480"))
    TARGET_FPS: int = int(os.getenv("TARGET_FPS", "15"))

    # Proctoring thresholds (monotonic duration in seconds)
    FACE_ABSENCE_THRESHOLD_SEC: float = float(os.getenv("FACE_ABSENCE_THRESHOLD_SEC", "5.0"))
    MULTIPLE_FACES_THRESHOLD_SEC: float = float(os.getenv("MULTIPLE_FACES_THRESHOLD_SEC", "2.0"))

    # Dashboard Server settings
    DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "5001"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "proctoring-default-dev-secret-key")

    # Raspberry Pi integration
    PI_ENABLED: bool = os.getenv("PI_ENABLED", "false").strip().lower() in ("true", "1", "yes")
    PI_BASE_URL: str = os.getenv("PI_BASE_URL", "http://raspberrypi.local:5050").rstrip("/")
    PI_SHARED_TOKEN: str = os.getenv("PI_SHARED_TOKEN", "")
    PI_TIMEOUT_SEC: float = float(os.getenv("PI_TIMEOUT_SEC", "2.0"))

    # Servo motor hardware settings (for Raspberry Pi agent)
    SERVO_ENABLED: bool = os.getenv("SERVO_ENABLED", "false").strip().lower() in ("true", "1", "yes")
    SERVO_DRY_RUN: bool = os.getenv("SERVO_DRY_RUN", "true").strip().lower() in ("true", "1", "yes")
    SERVO_PIN: int = int(os.getenv("SERVO_PIN", "18"))
    SERVO_MIN_PULSE_MS: float = float(os.getenv("SERVO_MIN_PULSE_MS", "1.0"))
    SERVO_MAX_PULSE_MS: float = float(os.getenv("SERVO_MAX_PULSE_MS", "2.0"))
    SERVO_FREQUENCY_HZ: int = int(os.getenv("SERVO_FREQUENCY_HZ", "50"))

    # Optional experimental features
    HEAD_POSE_ENABLED: bool = os.getenv("HEAD_POSE_ENABLED", "false").strip().lower() in ("true", "1", "yes")

    @classmethod
    def ensure_directories(cls) -> None:
        """Create necessary directories if they do not exist."""
        cls.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)


# Automatically ensure directories exist when config is imported
Config.ensure_directories()
