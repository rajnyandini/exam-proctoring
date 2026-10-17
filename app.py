"""Flask Web Application and REST API for Exam Proctoring Dashboard.

Binds locally to 127.0.0.1, multiplexes a single shared camera stream over MJPEG,
provides live proctoring telemetry, session controls, and evidence review.
"""

from __future__ import annotations

import logging
import time
from typing import Generator, Optional
import cv2
import numpy as np
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from config import Config
from proctor.camera import CameraManager
from proctor.face_detector import FaceDetector
from proctor.event_logger import EventLogger
from proctor.pi_client import RaspberryPiClient
from proctor.monitoring import MonitoringService

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("ProctorApp")


def create_app(
    synthetic_camera: bool = False,
    override_config: Optional[dict] = None,
) -> Flask:
    """Application factory for Flask app."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = Config.SECRET_KEY

    # Instantiate single shared services
    camera = CameraManager.get_instance(
        camera_index=Config.CAMERA_INDEX,
        backend_name=Config.CAMERA_BACKEND,
        width=Config.FRAME_WIDTH,
        height=Config.FRAME_HEIGHT,
        fps=Config.TARGET_FPS,
        synthetic=synthetic_camera,
    )

    detector = FaceDetector()
    event_logger = EventLogger(
        db_path=Config.DB_PATH,
        evidence_dir=Config.EVIDENCE_DIR,
    )
    pi_client = RaspberryPiClient(
        base_url=Config.PI_BASE_URL,
        shared_token=Config.PI_SHARED_TOKEN,
        timeout_sec=Config.PI_TIMEOUT_SEC,
        enabled=Config.PI_ENABLED,
    )

    monitoring_service = MonitoringService(
        camera=camera,
        detector=detector,
        logger_service=event_logger,
        pi_client=pi_client,
        face_absence_threshold_sec=Config.FACE_ABSENCE_THRESHOLD_SEC,
        multiple_faces_threshold_sec=Config.MULTIPLE_FACES_THRESHOLD_SEC,
    )

    # Attach services to app context for access in route handlers and tests
    app.camera = camera
    app.detector = detector
    app.event_logger = event_logger
    app.pi_client = pi_client
    app.monitoring_service = monitoring_service

    # --- HTML Routes ---
    @app.route("/")
    def index():
        """Render the main Proctoring Dashboard."""
        return render_template(
            "index.html",
            absence_threshold=Config.FACE_ABSENCE_THRESHOLD_SEC,
            multiple_threshold=Config.MULTIPLE_FACES_THRESHOLD_SEC,
            pi_enabled=Config.PI_ENABLED,
            pi_base_url=Config.PI_BASE_URL,
        )

    # --- Video Streaming Route ---
    def generate_mjpeg_frames() -> Generator[bytes, None, None]:
        """Yield multipart MJPEG frame chunks encoded from the shared monitoring pipeline."""
        target_delay = 1.0 / max(1, Config.TARGET_FPS)
        while True:
            frame = monitoring_service.get_annotated_frame()
            if frame is None:
                # Generate fallback offline frame
                frame = np.full((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), 25, dtype=np.uint8)
                cv2.putText(
                    frame,
                    "CAMERA FEED OFFLINE / STOPPED",
                    (50, Config.FRAME_HEIGHT // 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
                time.sleep(0.1)

            ret, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ret:
                time.sleep(0.05)
                continue

            frame_bytes = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(target_delay)

    @app.route("/video_feed")
    def video_feed():
        """Serve live annotated MJPEG video stream."""
        return Response(
            generate_mjpeg_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    # --- REST API Endpoints ---
    @app.route("/api/status", methods=["GET"])
    def get_status():
        """Real-time monitoring telemetry endpoint."""
        telemetry = monitoring_service.get_telemetry()
        cam_status = camera.get_status()
        pi_status = pi_client.get_status()

        return jsonify({
            "is_active": telemetry.is_active,
            "session_id": telemetry.session_id,
            "session_start_time": telemetry.session_start_time,
            "elapsed_seconds": round(telemetry.elapsed_seconds, 1),
            "current_status": telemetry.current_status,
            "face_count": telemetry.face_count,
            "active_anomaly": telemetry.active_anomaly,
            "absence_elapsed_sec": round(telemetry.absence_elapsed_sec, 1),
            "multiple_elapsed_sec": round(telemetry.multiple_elapsed_sec, 1),
            "camera": {
                "online": cam_status.is_open,
                "index": cam_status.camera_index,
                "backend": cam_status.backend,
                "width": cam_status.width,
                "height": cam_status.height,
                "fps": cam_status.fps,
                "error": cam_status.error_message,
            },
            "pi": {
                "enabled": pi_status.enabled,
                "online": pi_status.online,
                "base_url": pi_status.base_url,
                "last_error": pi_status.last_error,
            },
            "event_counts": telemetry.event_counts,
        })

    @app.route("/api/session/start", methods=["POST"])
    def start_session():
        """Start or restart a proctoring session."""
        session_id = monitoring_service.start_session()
        return jsonify({"success": True, "session_id": session_id})

    @app.route("/api/session/stop", methods=["POST"])
    def stop_session():
        """Stop the currently active session."""
        monitoring_service.stop_session()
        return jsonify({"success": True, "message": "Session stopped."})

    @app.route("/api/events", methods=["GET"])
    def get_events():
        """Fetch list of recent flagged events."""
        limit = request.args.get("limit", default=50, type=int)
        events = event_logger.get_recent_events(limit=limit)
        return jsonify({"events": events})

    @app.route("/api/events/clear", methods=["POST"])
    def clear_events():
        """Clear all logged events and associated evidence files."""
        count = event_logger.clear_events()
        return jsonify({"success": True, "cleared_count": count})

    @app.route("/evidence/<filename>")
    def get_evidence(filename: str):
        """Serve secure evidence snapshot file."""
        # Sanitize filename against directory traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            abort(400, "Invalid filename")
        return send_from_directory(Config.EVIDENCE_DIR, filename)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host=Config.DASHBOARD_HOST,
        port=Config.DASHBOARD_PORT,
        debug=False,
        threaded=True,
    )
