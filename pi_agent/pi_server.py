"""Raspberry Pi 3 Model B Central Proctoring Command Center Agent.

Supports receiving concurrent proctoring alerts from MULTIPLE candidate workstations
(e.g., student laptops and desktops across an examination hall). Tracks individual
workstation telemetry, flags incidents on a real-time Command Center dashboard,
and commands the indicator servo motor when any active workstation triggers an alert.
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

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [PiServer] %(message)s",
)
logger = logging.getLogger("PiServer")

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)

# --- Configuration ---
SHARED_TOKEN = os.getenv("PI_SHARED_TOKEN", "")
SERVO_ENABLED = os.getenv("SERVO_ENABLED", "false").strip().lower() in ("true", "1", "yes")
SERVO_DRY_RUN = os.getenv("SERVO_DRY_RUN", "true").strip().lower() in ("true", "1", "yes")
SERVO_PIN = int(os.getenv("SERVO_PIN", "18"))  # Proposed GPIO18 (BCM Pin 18, Physical Pin 12)
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
        """Attempt to initialize hardware PWM via gpiozero."""
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
        """Command servo position: ALERT (+45 deg), NORMAL (-45 deg), IDLE (0 deg)."""
        target_state = "ALERT" if status == "ALERT" else ("NORMAL" if status == "NORMAL" else "IDLE")
        target_angle = 45 if target_state == "ALERT" else (-45 if target_state == "NORMAL" else 0)
        self._current_angle = target_angle

        if self.dry_run or not self.enabled:
            msg = (
                f"[DRY-RUN SIMULATION] Would actuate servo on GPIO{self.pin} to "
                f"position {target_state} ({target_angle} deg). Physical actuation is DISABLED."
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


class WorkstationRecord:
    """Telemetry data structure for a single candidate workstation."""

    def __init__(self, device_id: str, candidate_name: str = "Candidate", ip_address: str = ""):
        self.device_id = device_id
        self.candidate_name = candidate_name
        self.ip_address = ip_address
        self.current_status = "NORMAL"
        self.event_type = "NORMAL"
        self.face_count = 1
        self.explanation = "Workstation initialized and monitored."
        self.last_timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        self.last_seen_epoch = time.time()
        self.total_alerts = 0
        self.history_count = 0
        self.evidence_image: Optional[str] = None
        self.alert_start_epoch: Optional[float] = None
        self.acknowledged: bool = False
        self.desk_history: collections.deque = collections.deque(maxlen=20)

    def update(
        self,
        status: str,
        event_type: str,
        face_count: int,
        explanation: str,
        timestamp: str,
        ip: str,
        candidate_name: Optional[str] = None,
        evidence_image: Optional[str] = None,
    ):
        prev_status = self.current_status
        self.current_status = status
        self.event_type = event_type
        self.face_count = face_count
        self.explanation = explanation
        self.last_timestamp = timestamp
        self.last_seen_epoch = time.time()
        self.history_count += 1
        if ip:
            self.ip_address = ip
        if candidate_name and candidate_name != "Candidate":
            self.candidate_name = candidate_name

        if status == "ALERT":
            if prev_status != "ALERT" or self.alert_start_epoch is None:
                self.alert_start_epoch = time.time()
                self.acknowledged = False
            self.total_alerts += 1
            if evidence_image:
                self.evidence_image = evidence_image
        elif status == "NORMAL":
            self.alert_start_epoch = None
            self.acknowledged = False

        self.desk_history.appendleft({
            "timestamp": timestamp,
            "status": status,
            "event_type": event_type,
            "face_count": face_count,
            "explanation": explanation,
            "evidence_image": evidence_image,
        })

    def to_dict(self) -> Dict[str, Any]:
        seconds_ago = round(time.time() - self.last_seen_epoch, 1)
        # Active if updated within the last 25 seconds
        is_active = seconds_ago < 25.0
        alert_duration = (
            round(time.time() - self.alert_start_epoch, 1)
            if (self.alert_start_epoch and self.current_status == "ALERT")
            else 0.0
        )
        return {
            "device_id": self.device_id,
            "candidate_name": self.candidate_name,
            "ip_address": self.ip_address,
            "current_status": self.current_status if is_active else "OFFLINE",
            "event_type": self.event_type,
            "face_count": self.face_count,
            "explanation": self.explanation,
            "last_timestamp": self.last_timestamp,
            "seconds_since_seen": seconds_ago,
            "is_active": is_active,
            "total_alerts": self.total_alerts,
            "alert_duration_sec": alert_duration,
            "acknowledged": self.acknowledged,
            "evidence_image": self.evidence_image,
            "history": list(self.desk_history),
        }


class MultiDeviceMonitorState:
    """Central store coordinating multiple candidate workstations and overall room status."""

    def __init__(self, max_history: int = 50) -> None:
        self._lock = threading.Lock()
        self.workstations: Dict[str, WorkstationRecord] = {}
        self.event_history: collections.deque = collections.deque(maxlen=max_history)
        self.total_events_recorded = 0

    def record_update(
        self,
        device_id: str,
        candidate_name: str,
        status: str,
        event_type: str,
        face_count: int,
        explanation: str,
        timestamp: Optional[str],
        ip_address: str,
        evidence_image: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Record workstation update and evaluate overall room proctoring status."""
        now_iso = timestamp or datetime.now(timezone.utc).astimezone().isoformat()
        clean_device = (device_id or "UNKNOWN-DESK").strip().upper()

        with self._lock:
            if clean_device not in self.workstations:
                self.workstations[clean_device] = WorkstationRecord(
                    device_id=clean_device,
                    candidate_name=candidate_name or "Candidate",
                    ip_address=ip_address,
                )

            station = self.workstations[clean_device]
            station.update(
                status=status,
                event_type=event_type,
                face_count=face_count,
                explanation=explanation,
                timestamp=now_iso,
                ip=ip_address,
                candidate_name=candidate_name,
                evidence_image=evidence_image,
            )

            self.total_events_recorded += 1
            self.event_history.appendleft({
                "index": self.total_events_recorded,
                "timestamp": now_iso,
                "device_id": clean_device,
                "candidate_name": station.candidate_name,
                "status": status,
                "event_type": event_type,
                "face_count": face_count,
                "explanation": explanation,
                "evidence_image": evidence_image,
            })

            # Calculate overall room status
            overall_status = self._compute_overall_status_unlocked()

        # Actuate servo based on overall hall status
        success, action_msg = servo.set_position(overall_status)
        return overall_status, action_msg

    def _compute_overall_status_unlocked(self) -> str:
        """Evaluate room status across active workstations: ALERT if ANY alert, NORMAL if all nominal."""
        now = time.time()
        active_stations = [s for s in self.workstations.values() if (now - s.last_seen_epoch) < 25.0]

        if not active_stations:
            return "IDLE"

        for s in active_stations:
            if s.current_status == "ALERT":
                return "ALERT"

        return "NORMAL"

    def get_snapshot(self) -> Dict[str, Any]:
        """Return real-time room overview, workstation grid, and incident audit log."""
        with self._lock:
            now = time.time()
            station_list = [s.to_dict() for s in self.workstations.values()]
            # Sort stations alphabetically by device_id
            station_list.sort(key=lambda s: s["device_id"])

            active_stations = [s for s in station_list if s["is_active"]]
            alert_stations = [s for s in active_stations if s["current_status"] == "ALERT"]
            nominal_stations = [s for s in active_stations if s["current_status"] == "NORMAL"]

            if not active_stations:
                overall_status = "IDLE"
            elif alert_stations:
                overall_status = "ALERT"
            else:
                overall_status = "NORMAL"

            latest_event = self.event_history[0] if self.event_history else None
            latest_type = latest_event["event_type"] if latest_event else "NORMAL"
            latest_faces = latest_event["face_count"] if latest_event else 1
            total_alerts = sum(1 for e in self.event_history if e.get("status") == "ALERT")

            return {
                "overall_status": overall_status,
                "current_status": overall_status if overall_status != "IDLE" else "NORMAL",
                "event_type": latest_type,
                "face_count": latest_faces,
                "total_alerts": total_alerts,
                "active_count": len(active_stations),
                "alert_count": len(alert_stations),
                "nominal_count": len(nominal_stations),
                "total_registered": len(station_list),
                "total_events": self.total_events_recorded,
                "servo": {
                    "enabled": servo.enabled,
                    "dry_run": servo.dry_run,
                    "pin": servo.pin,
                    "state": servo._current_state,
                    "angle": servo._current_angle,
                },
                "workstations": station_list,
                "history": list(self.event_history),
            }

    def clear_history(self) -> None:
        with self._lock:
            self.event_history.clear()
            self.total_events_recorded = 0

    def reset(self) -> None:
        """Reset all state (stations, history, counters) for test isolation."""
        with self._lock:
            self.workstations.clear()
            self.event_history.clear()
            self.total_events_recorded = 0

    def clear_inactive(self) -> int:
        with self._lock:
            now = time.time()
            to_remove = [k for k, s in self.workstations.items() if (now - s.last_seen_epoch) >= 25.0]
            for k in to_remove:
                del self.workstations[k]
            return len(to_remove)

    def acknowledge_station(self, device_id: str) -> bool:
        """Mark alert for a specific workstation as acknowledged by proctor."""
        clean_device = (device_id or "").strip().upper()
        with self._lock:
            station = self.workstations.get(clean_device)
            if station:
                station.acknowledged = True
                return True
            return False

    def acknowledge_all(self) -> int:
        """Mark all active alerts as acknowledged by proctor."""
        with self._lock:
            count = 0
            for s in self.workstations.values():
                if s.current_status == "ALERT" and not s.acknowledged:
                    s.acknowledged = True
                    count += 1
            return count

    def get_audit_report(self) -> Dict[str, Any]:
        """Generate structured audit report of all workstations and incidents."""
        with self._lock:
            return {
                "system": "Exam Proctoring Command Center",
                "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "total_events": self.total_events_recorded,
                "workstations": [s.to_dict() for s in self.workstations.values()],
                "history": list(self.event_history),
            }


# Global multi-device state manager
monitor_state = MultiDeviceMonitorState()


def verify_authentication() -> Optional[Tuple[Dict[str, str], int]]:
    """Validate incoming request authorization against the configured SHARED_TOKEN."""
    if not SHARED_TOKEN:
        logger.warning("PI_SHARED_TOKEN is unset in environment. Rejecting request for security.")
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


# --- Web Dashboard & Public API ---

@app.route("/", methods=["GET"])
def dashboard_view():
    """Serve the multi-workstation Real Exam Proctoring Command Center."""
    return render_template(
        "index.html",
        servo_enabled=servo.enabled,
        servo_dry_run=servo.dry_run,
        servo_pin=servo.pin,
        auth_configured=bool(SHARED_TOKEN),
        auth_token=SHARED_TOKEN,
    )


@app.route("/api/status", methods=["GET"])
def get_dashboard_status():
    """Real-time JSON endpoint polled by the Command Center dashboard."""
    return jsonify(monitor_state.get_snapshot()), 200


@app.route("/api/clear_inactive", methods=["POST"])
def clear_inactive_stations():
    """Prune disconnected/offline workstations from the active monitoring grid."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]
    cleared = monitor_state.clear_inactive()
    return jsonify({"acknowledged": True, "cleared_count": cleared}), 200


@app.route("/api/clear_history", methods=["POST"])
def clear_dashboard_history():
    """Clear incident history stream."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]
    monitor_state.clear_history()
    return jsonify({"acknowledged": True, "message": "Incident history cleared"}), 200


@app.route("/api/workstation/<device_id>/acknowledge", methods=["POST"])
def acknowledge_workstation(device_id: str):
    """Proctor acknowledges/reviews active alert for a specific workstation."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]
    success = monitor_state.acknowledge_station(device_id)
    return jsonify({"acknowledged": success, "device_id": device_id}), 200


@app.route("/api/acknowledge_all", methods=["POST"])
def acknowledge_all_alerts():
    """Proctor acknowledges all active alerts across the exam hall."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]
    count = monitor_state.acknowledge_all()
    return jsonify({"acknowledged": True, "count": count}), 200


@app.route("/api/export_report", methods=["GET"])
def export_audit_report():
    """Export complete exam proctoring audit log as JSON."""
    report = monitor_state.get_audit_report()
    return jsonify(report), 200


@app.route("/api/simulate_multi", methods=["POST"])
def simulate_multi_workstations():
    """Simulate a realistic multi-device exam hall with multiple students."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]

    sim_stations = [
        {
            "id": "DESK-01",
            "name": "Sarah Connor",
            "status": "NORMAL",
            "type": "NORMAL",
            "faces": 1,
            "exp": "Single candidate face verified within bounding bounds.",
            "ip": "192.168.1.101",
        },
        {
            "id": "DESK-02",
            "name": "Alex Mercer",
            "status": "ALERT",
            "type": "FACE_ABSENT",
            "faces": 0,
            "exp": "Candidate left workstation for > 5.0 seconds. Flagged for review.",
            "ip": "192.168.1.102",
        },
        {
            "id": "DESK-03",
            "name": "Elena Fisher",
            "status": "ALERT",
            "type": "MULTIPLE_FACES",
            "faces": 2,
            "exp": "Second face detected in candidate field of view. Potential collusion.",
            "ip": "192.168.1.103",
        },
        {
            "id": "DESK-04",
            "name": "James Holden",
            "status": "NORMAL",
            "type": "NORMAL",
            "faces": 1,
            "exp": "Nominal candidate presence maintained.",
            "ip": "192.168.1.104",
        },
    ]

    for s in sim_stations:
        monitor_state.record_update(
            device_id=s["id"],
            candidate_name=s["name"],
            status=s["status"],
            event_type=s["type"],
            face_count=s["faces"],
            explanation=s["exp"],
            timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
            ip_address=s["ip"],
        )

    return jsonify({"success": True, "simulated_count": len(sim_stations)}), 200


@app.route("/api/simulate_station", methods=["POST"])
def simulate_station():
    """Proctor test helper: simulate an additional workstation sending updates."""
    auth_err = verify_authentication()
    if auth_err:
        return jsonify(auth_err[0]), auth_err[1]

    data = request.get_json(silent=True) or {}
    dev_id = data.get("device_id", "DESK-TEST")
    cand_name = data.get("candidate_name", "Test Candidate")
    status = data.get("status", "ALERT")
    event_type = data.get("event_type", "MULTIPLE_FACES")
    face_count = data.get("face_count", 2)
    explanation = data.get("explanation", "Simulated multi-candidate alert for proctor testing.")
    evidence_image = data.get("evidence_image")

    overall, msg = monitor_state.record_update(
        device_id=dev_id,
        candidate_name=cand_name,
        status=status,
        event_type=event_type,
        face_count=face_count,
        explanation=explanation,
        timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
        ip_address=request.remote_addr or "127.0.0.1",
        evidence_image=evidence_image,
    )

    return jsonify({
        "simulated": True,
        "device_id": dev_id,
        "overall_status": overall,
        "servo_action": msg,
    }), 200


# --- External Proctoring Ingestion API ---

@app.route("/health", methods=["GET"])
def health_check():
    """Public diagnostic health check endpoint used by client heartbeat/liveness probes."""
    snap = monitor_state.get_snapshot()
    return jsonify({
        "status": "online",
        "device": "Raspberry Pi 3 Model B Command Center",
        "overall_status": snap["overall_status"],
        "active_workstations": snap["active_count"],
        "dry_run": servo.dry_run,
        "servo_enabled": servo.enabled,
        "servo_pin": servo.pin,
        "current_indicator_state": servo._current_state,
        "auth_configured": bool(SHARED_TOKEN),
    }), 200


@app.route("/status", methods=["POST"])
def update_status():
    """Authenticated endpoint receiving real-time proctoring updates from exam workstations."""
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
    device_id = data.get("device_id", f"STATION-{request.remote_addr or 'UNKNOWN'}")
    candidate_name = data.get("candidate_name", "Candidate")

    # Strict validation of status values
    if status not in ("NORMAL", "ALERT"):
        return jsonify({
            "error": "Invalid status field. Allowed values: 'NORMAL', 'ALERT'"
        }), 400

    logger.info(
        f"[{device_id} - {candidate_name}] Status={status}, Event={event_type}, "
        f"Faces={face_count}, Detail='{explanation}'"
    )

    evidence_image = data.get("evidence_image")

    overall_status, servo_action = monitor_state.record_update(
        device_id=device_id,
        candidate_name=candidate_name,
        status=status,
        event_type=event_type,
        face_count=face_count,
        explanation=explanation,
        timestamp=timestamp,
        ip_address=request.remote_addr or "127.0.0.1",
        evidence_image=evidence_image,
    )

    return jsonify({
        "acknowledged": True,
        "received_device": device_id,
        "received_status": status,
        "overall_room_status": overall_status,
        "servo_action": servo_action,
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
        f"Starting Raspberry Pi Command Center on {PI_HOST}:{PI_PORT}\n"
        f"Servo Enabled: {SERVO_ENABLED} | Dry Run Mode: {SERVO_DRY_RUN} | Pin: GPIO{SERVO_PIN}"
    )
    app.run(host=PI_HOST, port=PI_PORT, debug=False)
