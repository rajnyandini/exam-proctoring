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
        "--camera",
        default=Config.CAMERA_SOURCE,
        help="Camera selection mode: 'native' (built-in camera), 'external' (USB webcam), 'auto', or numeric index (default: auto)",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=Config.CAMERA_INDEX,
        help=f"Specific camera index (default: {Config.CAMERA_INDEX})",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="Scan and list detected video camera devices on this machine, then exit",
    )
    parser.add_argument(
        "--device-id",
        default=Config.DEVICE_ID,
        help=f"Workstation / Desk ID for multi-device proctoring (default: {Config.DEVICE_ID})",
    )
    parser.add_argument(
        "--candidate-name",
        default=Config.CANDIDATE_NAME,
        help=f"Candidate / Student name (default: {Config.CANDIDATE_NAME})",
    )
    parser.add_argument(
        "--pi-url",
        default=Config.PI_BASE_URL,
        help=f"Raspberry Pi Command Center URL (default: {Config.PI_BASE_URL})",
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

    if args.list_cameras:
        from proctor.camera import CameraManager
        print("\nScanning for available cameras...")
        cams = CameraManager.scan_available_cameras(Config.CAMERA_BACKEND)
        if not cams:
            print("No active cameras detected. Check permissions or USB connections.")
        else:
            print(f"Found {len(cams)} camera(s):")
            for c in cams:
                print(f"  [{c['index']}] {c['label']} ({c['width']}x{c['height']})")
        sys.exit(0)

    # Determine camera source and index
    cam_source = str(args.camera).strip().lower()
    cam_idx = args.camera_index
    if cam_source == "native":
        cam_idx = 0
    elif cam_source == "external":
        cam_idx = 1 if args.camera_index == 0 else args.camera_index
    elif cam_source.isdigit():
        cam_idx = int(cam_source)

    pi_url = args.pi_url.rstrip("/")
    if pi_url != Config.PI_BASE_URL:
        Config.PI_BASE_URL = pi_url
        Config.PI_ENABLED = True

    print("\n" + "=" * 65)
    print("        AI-POWERED EXAM PROCTORING SYSTEM (PROTOTYPE)")
    print("=" * 65)
    print(f" * Workstation ID:     {args.device_id} ({args.candidate_name})")
    print(f" * Dashboard URL:      http://{args.host}:{args.port}")
    print(f" * Camera Target:      Index {cam_idx} (Source: {cam_source.upper()}, Auto-Detect: {'ON' if Config.CAMERA_AUTO_DETECT else 'OFF'})")
    print(f" * Requested Capture:  {Config.FRAME_WIDTH}x{Config.FRAME_HEIGHT} @ {Config.TARGET_FPS} FPS")
    print(f" * Absence Threshold:  {Config.FACE_ABSENCE_THRESHOLD_SEC} seconds")
    print(f" * Multiple Threshold: {Config.MULTIPLE_FACES_THRESHOLD_SEC} seconds")
    print(f" * Database Path:      {Config.DB_PATH}")
    print(f" * Evidence Folder:    {Config.EVIDENCE_DIR}")
    print(f" * Raspberry Pi Link:  {'ENABLED -> ' + Config.PI_BASE_URL if Config.PI_ENABLED else 'DISABLED (Local Only)'}")
    print(f" * Synthetic Camera:   {'YES' if args.synthetic else 'NO (Hardware Webcam)'}")
    print("=" * 65)
    print(" [NOTICE] Detections are indicators for human review, not proof of cheating.")
    print(" Press Ctrl+C in this terminal to shut down cleanly.\n")

    override_cfg = {
        "DEVICE_ID": args.device_id,
        "CANDIDATE_NAME": args.candidate_name,
        "CAMERA_INDEX": cam_idx,
        "CAMERA_SOURCE": cam_source,
    }
    app = create_app(synthetic_camera=args.synthetic, override_config=override_cfg)

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
