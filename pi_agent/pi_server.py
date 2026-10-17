"""Raspberry Pi 3 Model B Status & Hardware Controller Agent.

A secure, lightweight Flask service designed to run on the Raspberry Pi 3 Model B.
Receives authenticated status notifications from the MacBook proctoring system,
serves a clean browser-based live status dashboard, and provides safe, opt-in
servo motor alerting with conservative default guardrails.
"""

from __future__ import annotations

import collections
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from flask import Flask, jsonify, render_template, request

# Base directory for pi_agent assets
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [PiAgent] %(message)s",
)
logger = logging.getLogger("PiAgent")

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)

# --- Environment Configuration ---
SHARED_TOKEN = os.getenv("PI_SHARED_TOKEN", "")
SERVO_ENABLED = os.getenv("SERVO_ENABLED", "false").strip().lower() in ("true", "1", "yes")
SERVO_DRY_RUN = os.getenv("SERVO_DRY_RUN", "true").strip().lower() in ("true", "1", "yes")
SERVO_PIN = int(os.getenv("SERVO_PIN", "18"))  # Proposed GPIO18 (BCM Pin 18, Header Pin 12)
PI_PORT = int(os.getenv("PI_PORT", "5050"))
PI_HOST = os.getenv("PI_HOST", "0.0.0.0")


class ServoController:
    """Safe servo hardware controller with dry-run protection and electrical guardrails."""

    def __init__(
        self,
        enabled: bool = False,
        dry_run: bool = True,
        pin: int = 18,
    ) -> None:
        self.enabled = enabled
        self.dry_run = dry_run
        self.pin = pin
        self._servo_device = None
        self._current_state = "IDLE"
        self._current_angle = 0

        if self.enabled and not self.dry_run:
            self._init_hardware()
        else:
            logger.info(
                f"Servo initialized in SAFE MODE (enabled={self.enabled}, dry_run={self.dry_run}). "
                "No physical pulses will be sent."
            )

    def _init_hardware(self) -> None:
        """Attempt to initialize hardware PWM or gpiozero."""
        logger.warning(
            "*** HARDWARE SERVO INITIALIZATION REQUESTED ***\n"
            "SAFETY CHECKLIST:\n"
            "1. Verified servo operating voltage (4.8V - 6.0V typical)?\n"
            "2. Powered from dedicated external 5V regulated power supply (NOT Raspberry Pi 3.3V/5V header)?\n"
            "3. Common ground shared between external power supply GND and Raspberry Pi GND?\n"
            f"4. Signal wire connected to BCM GPIO{self.pin}?"
        )
        try:
            from gpiozero import AngularServo
            # Standard conservative 50Hz PWM pulse settings (1.0ms - 2.0ms)
            self._servo_device = AngularServo(
                self.pin,
                min_angle=-90,
                max_angle=90,
                min_pulse_width=0.001,
                max_pulse_width=0.002,
            )
            logger.info(f"Initialized AngularServo on BCM GPIO{self.pin}.")
        except ImportError:
            logger.error(
                "gpiozero library not installed. Falling back to dry-run simulation mode. "
                "Run 'pip install gpiozero pigpio' on Raspberry Pi OS."
            )
            self.dry_run = True
        except Exception as e:
            logger.error(f"Hardware initialization failed on GPIO{self.pin}: {e}. Falling back to dry-run.")
            self.dry_run = True

    def set_position(self, status: str) -> Tuple[bool, str]:
        """Command servo to visual indicator position based on status."""
        target_state = "ALERT" if status == "ALERT" else "NORMAL"
        target_angle = 45 if target_state == "ALERT" else -45
        self._current_angle = target_angle

        if self.dry_run or not self.enabled:
            msg = (
                f"[DRY-RUN SIMULATION] Would actuate servo on GPIO{self.pin} to "
                f"position {target_state} (approx angle: {target_angle} deg). "
                f"Physical actuation is DISABLED."
            )
            logger.info(msg)
            self._current_state = target_state
            return True, msg

        if self._servo_device is not None:
            try:
                self._servo_device.angle = target_angle
                msg = f"Actuated physical servo to angle {target_angle} deg ({target_state})."
                logger.info(msg)
                self._current_state = target_state
                return True, msg
            except Exception as e:
                err = f"Failed to move physical servo on GPIO{self.pin}: {e}"
                logger.error(err)
                return False, err

        return False, "Servo controller uninitialized."


# Global controller instance
servo = ServoController(
    enabled=SERVO_ENABLED,
    dry_run=SERVO_DRY_RUN,
    pin=SERVO_PIN,
)


class PiMonitorState:
    """In-memory state and recent history store for the Raspberry Pi live dashboard."""

    def __init__(self, max_history: int = 30) -> None:
        self._lock = threading.Lock()
        self.current_status = "IDLE"
        self.event_type = "NONE"
        self.face_count = 0
        self.explanation = "Awaiting initial status update from MacBook."
        self.last_timestamp: Optional[str] = None
        self.last_received_epoch: float = 0.0
        self.total_alerts: int = 0
        self.total_updates: int = 0
        self.history: collections.deque = collections.deque(maxlen=max_history)

    def record_update(
        self,
        status: str,
        event_type: str,
        face_count: int,
        explanation: str,
        timestamp: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.current_status = status
            self.event_type = event_type
            self.face_count = face_count
            self.explanation = explanation
            now_iso = timestamp or datetime.now(timezone.utc).astimezone().isoformat()
            self.last_timestamp = now_iso
            self.last_received_epoch = time.time()
            self.total_updates += 1
            if status == "ALERT":
                self.total_alerts += 1

            self.history.appendleft({
                "index": self.total_updates,
                "timestamp": now_iso,
                "status": status,
                "event_type": event_type,
                "face_count": face_count,
                "explanation": explanation,
            })

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            time_since = round(now - self.last_received_epoch, 1) if self.last_received_epoch > 0 else None
            # Consider connected if an update arrived within the last 30 seconds
            is_connected = time_since is not None and time_since < 30.0

            return {
                "current_status": self.current_status,
                "event_type": self.event_type,
                "face_count": self.face_count,
                "explanation": self.explanation,
                "last_timestamp": self.last_timestamp,
                "seconds_since_update": time_since,
                "is_connected": is_connected,
                "total_alerts": self.total_alerts,
                "total_updates": self.total_updates,
                "servo": {
                    "enabled": servo.enabled,
                    "dry_run": servo.dry_run,
                    "pin": servo.pin,
                    "state": servo._current_state,
                    "angle": servo._current_angle,
                },
                "history": list(self.history),
            }

    def clear_history(self) -> None:
        with self._lock:
            self.history.clear()
            self.total_alerts = 0
            self.total_updates = 0


# Global state store
monitor_state = PiMonitorState()


def verify_authentication() -> Optional[Tuple[Dict[str, str], int]]:
    """Validate incoming request authorization against the configured SHARED_TOKEN."""
    if not SHARED_TOKEN:
        logger.warning(
            "PI_SHARED_TOKEN is unset in environment. Rejecting request for security."
        )
        return {"error": "Server unconfigured: PI_SHARED_TOKEN missing on Pi agent"}, 500

    auth_header = request.headers.get("Authorization", "")
    custom_header = request.headers.get("X-Proctor-Auth", "")

    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif custom_header:
        token = custom_header.strip()

    if not token or token != SHARED_TOKEN:
        logger.warning(f"Unauthorized access attempt from {request.remote_addr}.")
        return {"error": "Unauthorized: invalid or missing authentication token"}, 401

    return None


# --- Web Dashboard Routes ---

@app.route("/", methods=["GET"])
def dashboard_view():
    """Serve the clean, white-themed Raspberry Pi Live Status Dashboard."""
    state = monitor_state.get_snapshot()
    return render_template(
        "index.html",
        servo_enabled=servo.enabled,
        servo_dry_run=servo.dry_run,
        servo_pin=servo.pin,
        auth_configured=bool(SHARED_TOKEN),
    )


@app.route("/api/status", methods=["GET"])
def get_dashboard_status():
    """Unauthenticated polling endpoint for the local browser dashboard."""
    return jsonify(monitor_state.get_snapshot()), 200


@app.route("/api/clear_history", methods=["POST"])
def clear_dashboard_history():
    """Endpoint to reset event history on the dashboard."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]
    monitor_state.clear_history()
    return jsonify({"acknowledged": True, "message": "History cleared"}), 200


# --- External Proctoring API Endpoints ---

@app.route("/health", methods=["GET"])
def health_check():
    """Public diagnostic health check endpoint used by the MacBook client."""
    return jsonify({
        "status": "online",
        "device": "Raspberry Pi 3 Model B Agent",
        "dry_run": servo.dry_run,
        "servo_enabled": servo.enabled,
        "servo_pin": servo.pin,
        "current_indicator_state": servo._current_state,
        "auth_configured": bool(SHARED_TOKEN),
    }), 200


@app.route("/status", methods=["POST"])
def update_status():
    """Authenticated endpoint receiving proctoring status updates from MacBook."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]

    if not request.is_json:
        return jsonify({"error": "Payload must be JSON"}), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Malformed JSON object"}), 400

    status = data.get("status")
    event_type = data.get("event_type", "UNKNOWN")
    face_count = data.get("face_count", 0)
    explanation = data.get("explanation", "")
    timestamp = data.get("timestamp")

    # Strict validation of status values
    if status not in ("NORMAL", "ALERT"):
        return jsonify({
            "error": "Invalid status field. Allowed values: 'NORMAL', 'ALERT'"
        }), 400

    logger.info(
        f"Received verified status: [{status}] Event='{event_type}', "
        f"Faces={face_count}, Detail='{explanation}'"
    )

    # Record update into in-memory dashboard state
    monitor_state.record_update(
        status=status,
        event_type=event_type,
        face_count=face_count,
        explanation=explanation,
        timestamp=timestamp,
    )

    # Actuate or simulate servo motor
    success, action_message = servo.set_position(status)

    return jsonify({
        "acknowledged": True,
        "received_status": status,
        "servo_action": action_message,
    }), 200


@app.route("/test_servo", methods=["POST"])
def test_servo():
    """Authenticated endpoint to trigger a safe test cycle."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]

    target = request.args.get("state", "ALERT").upper()
    if target not in ("NORMAL", "ALERT"):
        target = "ALERT"

    success, msg = servo.set_position(target)
    monitor_state.record_update(
        status=target,
        event_type="TEST_TRIGGER",
        face_count=1 if target == "NORMAL" else 0,
        explanation=f"Manual test actuation: {msg}",
    )

    return jsonify({
        "test_executed": True,
        "target_state": target,
        "message": msg,
        "dry_run": servo.dry_run,
    }), 200


if __name__ == "__main__":
    if not SHARED_TOKEN:
        logger.error(
            "CRITICAL: PI_SHARED_TOKEN is not set in environment.\n"
            "Generate a random token (e.g. openssl rand -hex 16) and set it:\n"
            "export PI_SHARED_TOKEN='your_token_here'"
        )
    logger.info(
        f"Starting Raspberry Pi Proctoring Agent on {PI_HOST}:{PI_PORT}\n"
        f"Servo Enabled: {SERVO_ENABLED} | Dry Run Mode: {SERVO_DRY_RUN} | Pin: GPIO{SERVO_PIN}"
    )
    app.run(host=PI_HOST, port=PI_PORT, debug=False)
