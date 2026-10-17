#!/usr/bin/env python3
"""Launcher script for Exam Proctoring System.

Supports graceful shutdown (releasing camera handles and database connections),
optional synthetic camera mode for headless testing, and terminal status banner.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from config import Config
from app import create_app

logger = logging.getLogger("ProctorRunner")


def parse_args():
    parser = argparse.ArgumentParser(description="Exam Proctoring System")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Run with synthetic test camera instead of physical webcam (useful for tests/demos)",
    )
    parser.add_argument(
        "--host",
        default=Config.DASHBOARD_HOST,
        help=f"Host address to bind (default: {Config.DASHBOARD_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=Config.DASHBOARD_PORT,
        help=f"Port number to bind (default: {Config.DASHBOARD_PORT})",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("\n" + "=" * 65)
    print("        AI-POWERED EXAM PROCTORING SYSTEM (PROTOTYPE)")
    print("=" * 65)
    print(f" * Dashboard URL:      http://{args.host}:{args.port}")
    print(f" * Camera Backend:     {Config.CAMERA_BACKEND} (Index: {Config.CAMERA_INDEX})")
    print(f" * Requested Capture:  {Config.FRAME_WIDTH}x{Config.FRAME_HEIGHT} @ {Config.TARGET_FPS} FPS")
    print(f" * Absence Threshold:  {Config.FACE_ABSENCE_THRESHOLD_SEC} seconds")
    print(f" * Multiple Threshold: {Config.MULTIPLE_FACES_THRESHOLD_SEC} seconds")
    print(f" * Database Path:      {Config.DB_PATH}")
    print(f" * Evidence Folder:    {Config.EVIDENCE_DIR}")
    print(f" * Raspberry Pi Link:  {'ENABLED' if Config.PI_ENABLED else 'DISABLED (Local Only)'}")
    print(f" * Synthetic Camera:   {'YES' if args.synthetic else 'NO (Hardware Webcam)'}")
    print("=" * 65)
    print(" [NOTICE] Detections are indicators for human review, not proof of cheating.")
    print(" Press Ctrl+C in this terminal to shut down cleanly.\n")

    app = create_app(synthetic_camera=args.synthetic)

    def handle_shutdown(signum, frame):
        print("\n[Shutdown] Caught termination signal. Releasing resources...")
        try:
            if hasattr(app, "monitoring_service"):
                app.monitoring_service.stop_session()
            if hasattr(app, "camera"):
                app.camera.stop()
        except Exception as e:
            print(f"Error during shutdown: {e}")
        print("[Shutdown] Completed cleanly. Goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Automatically start session upon startup
    app.monitoring_service.start_session()

    app.run(
        host=args.host,
        port=args.port,
        debug=False,
        use_reloader=False,  # Reloader can fork multiple camera handles
        threaded=True,
    )


if __name__ == "__main__":
    main()
