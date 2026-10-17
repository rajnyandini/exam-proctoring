# AI-Powered Exam Proctoring System

A local-first, modular exam proctoring prototype designed to run real-time computer vision on a **MacBook** (macOS x86_64), provide a local web dashboard for proctors, and optionally send authenticated status notifications to a **Raspberry Pi 3 Model B** to actuate a physical indicator servo motor.

> [!IMPORTANT]
> **Academic Prototype & Human Review Notice**:
> This system is an academic engineering prototype. Automated computer vision events (such as face absence or multiple faces) are indicators flagged for human review—**not** conclusive proof of cheating or grounds for automated punishment. Lighting changes, facial occlusion, and hardware noise can generate false positives or false negatives.

---

## 1. System Architecture

The MacBook performs all video capture and computer vision processing. The Raspberry Pi handles hardware alert indication only.

```
+-------------------------------------------------------------------------------+
|                                 MacBook Air                                   |
|                                                                               |
|  [External USB Webcam]                                                        |
|           | (cv2.CAP_AVFOUNDATION, 640x480 @ 15 FPS)                          |
|           v                                                                   |
|   +---------------+         +-------------------+                             |
|   | CameraManager | ------> |   FaceDetector    | (Haar Cascade)              |
|   +---------------+         +-------------------+                             |
|           |                           |                                       |
|           |                           v                                       |
|           |                 +-------------------+                             |
|           |                 | MonitoringService | (Monotonic Timers:          |
|           |                 +-------------------+  Absence: 5s, Multiple: 2s) |
|           |                    |             |                                |
|           v                    v             v                                |
|     (MJPEG Stream)     (EventLogger)   (RaspberryPiClient)                    |
|           |            - SQLite DB     - Non-blocking HTTP                    |
|           |            - JPEG frames   - Bearer Token Auth                    |
|           v                    |             |                                |
|   +---------------+            |             | (Local Wi-Fi / Ethernet)       |
|   | Flask Server  | <----------+             |                                |
|   | (127.0.0.1)   |                          |                                |
|   +---------------+                          |                                |
|           |                                  |                                |
|           v                                  |                                |
|   [Web Dashboard]                            |                                |
+----------------------------------------------|--------------------------------+
                                               |
                                               v
                          +------------------------------------------+
                          |        Raspberry Pi 3 Model B            |
                          |                                          |
                          |  +------------------------------------+  |
                          |  |      pi_server.py (Flask API)      |  |
                          |  |  - Auth validation (Bearer token)  |  |
                          |  |  - Payload schema validation       |  |
                          |  +------------------------------------+  |
                          |                   |                      |
                          |                   v                      |
                          |  +------------------------------------+  |
                          |  |       ServoController (Safe)       |  |
                          |  |  - Disabled by default             |  |
                          |  |  - Dry-run simulation logging      |  |
                          |  +------------------------------------+  |
                          |                   |                      |
                          +-------------------|----------------------+
                                              | (GPIO 18 Signal)
                                              v
                              +--------------------------------+
                              |      Optional Servo Motor      |
                              |  - Powered by External 5V Reg  |
                              |  - Common Ground with Pi       |
                              +--------------------------------+
```

---

## 2. Directory Structure

```
exam_proctoring/
├── app.py                      # Flask web application & REST API
├── config.py                   # Central typed configuration & environment loader
├── requirements.txt            # MacBook Python dependencies
├── pytest.ini                  # Pytest test discovery & pythonpath configuration
├── README.md                   # System documentation & operating guide
├── .env.example                # Configuration template
├── .gitignore                  # VCS ignore rules (excludes .venv, evidence, db)
├── run.py                      # Application launcher with CLI arguments & shutdown traps
├── face_detection.py           # Original working face detection script (preserved)
├── face_detection_backup.py    # Backup of tested baseline detector
├── webcam_test.py              # Original working camera capture test script (preserved)
├── proctor/                    # Core proctoring Python package
│   ├── __init__.py             # Package exports
│   ├── camera.py               # Thread-safe camera manager (AVFoundation & synthetic mode)
│   ├── face_detector.py        # Haar Cascade detector & HUD telemetry overlay
│   ├── monitoring.py           # Temporal state machine, monotonic timers, duplicate suppression
│   ├── event_logger.py         # SQLite database logger & JPEG snapshot evidence saver
│   └── pi_client.py            # Resilient HTTP client for Raspberry Pi notifications
├── templates/
│   └── index.html              # Clean dark-slate proctoring dashboard
├── static/
│   ├── css/
│   │   └── style.css           # Modern responsive stylesheet & status animations
│   └── js/
│       └── app.js              # Live telemetry polling, modal preview, & session controls
├── pi_agent/                   # Raspberry Pi 3B subproject
│   ├── pi_server.py            # Lightweight authenticated Flask receiver
│   ├── requirements.txt        # Pi-specific dependencies
│   └── README.md               # Electrical safety guide & wiring instructions
├── tests/                      # Automated test suite (22 unit tests)
│   ├── test_app.py             # Dashboard API & routes tests
│   ├── test_event_logger.py    # Database, ISO 8601 timestamps, & snapshot tests
│   ├── test_face_detector.py   # Haar cascade & annotation tests
│   ├── test_monitoring.py      # Monotonic timers, thresholds, & suppression tests
│   └── test_pi_agent.py        # Pi server auth, payloads, dry-run, & client timeouts
├── evidence/                   # Saved JPEG snapshot frames (generated at runtime)
└── data/                       # Local SQLite database `proctoring.db` (generated at runtime)
```

---

## 3. MacBook Installation & Setup

### Prerequisites
- macOS on Intel x86_64 (or Apple Silicon).
- Python 3.12 (installed via Homebrew: `brew install python@3.12`).
- External USB webcam connected.

### Step 1: Activate Virtual Environment
```bash
cd ~/exam_proctoring
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```
*Dependencies:*
- `opencv-python==4.11.0.86` (pinned for `cv2.CascadeClassifier` compatibility)
- `flask>=3.0.0`
- `requests>=2.31.0`
- `python-dotenv>=1.0.0`
- `pytest>=8.0.0`

### Step 3: Configure Environment Variables
Copy the template configuration:
```bash
cp .env.example .env
```
Key settings in `.env`:
```ini
CAMERA_INDEX=0
CAMERA_BACKEND=AVFOUNDATION
FRAME_WIDTH=640
FRAME_HEIGHT=480
TARGET_FPS=15

FACE_ABSENCE_THRESHOLD_SEC=5.0
MULTIPLE_FACES_THRESHOLD_SEC=2.0

DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=5001

PI_ENABLED=false
PI_BASE_URL=http://raspberrypi.local:5050
PI_SHARED_TOKEN=your_token_here
```

### Step 4: macOS Camera Permissions
macOS restricts camera access at the operating system level.
1. Open **System Settings > Privacy & Security > Camera**.
2. Verify that your **Terminal** app (or **VS Code / Cursor / iTerm**) has camera permissions toggled **ON**.
3. If permissions were newly granted, restart your terminal.

---

## 4. Running the Application

### Option A: Standard Mode (Physical Webcam)
```bash
python run.py
```
Output:
```
=================================================================
        AI-POWERED EXAM PROCTORING SYSTEM (PROTOTYPE)
=================================================================
 * Dashboard URL:      http://127.0.0.1:5001
 * Camera Backend:     AVFOUNDATION (Index: 0)
 * Requested Capture:  640x480 @ 15 FPS
 * Absence Threshold:  5.0 seconds
 * Multiple Threshold: 2.0 seconds
 * Database Path:      /Users/bhallarunbir539/exam_proctoring/data/proctoring.db
 * Evidence Folder:    /Users/bhallarunbir539/exam_proctoring/evidence
 * Raspberry Pi Link:  DISABLED (Local Only)
 * Synthetic Camera:   NO (Hardware Webcam)
=================================================================
```

Open your browser to:
👉 **`http://127.0.0.1:5001`**

### Option B: Synthetic Test Camera Mode (Headless / No Webcam Attached)
To run or demo the application without connecting a physical webcam:
```bash
python run.py --synthetic --port 5001
```

### Stopping the Application
Press `Ctrl+C` in the terminal. The application catches `SIGINT` and cleanly shuts down the camera capture thread, releases AVFoundation handles, and closes database connections.

---

## 5. Running the Automated Test Suite

All tests use mocks or synthetic images and run in isolated sandboxes without requiring a physical camera or Raspberry Pi:

```bash
pytest -v
```

Expected output:
```
============================= test session starts ==============================
collected 22 items

tests/test_app.py::test_dashboard_index_route PASSED                     [  4%]
tests/test_app.py::test_api_status_route PASSED                          [  9%]
tests/test_app.py::test_api_session_lifecycle PASSED                     [ 13%]
tests/test_app.py::test_evidence_directory_traversal_protection PASSED   [ 18%]
tests/test_event_logger.py::test_event_creation_and_retrieval PASSED     [ 22%]
tests/test_event_logger.py::test_event_counts_aggregation PASSED         [ 27%]
tests/test_event_logger.py::test_clear_events PASSED                     [ 31%]
tests/test_event_logger.py::test_snapshot_write_failure_resilience PASSED [ 36%]
tests/test_face_detector.py::test_face_detector_initialization PASSED    [ 40%]
tests/test_face_detector.py::test_detect_on_blank_frame PASSED           [ 45%]
tests/test_face_detector.py::test_annotate_frame PASSED                  [ 50%]
tests/test_monitoring.py::test_normal_condition PASSED                   [ 54%]
tests/test_monitoring.py::test_face_absence_threshold_and_suppression PASSED [ 59%]
tests/test_monitoring.py::test_face_absence_reset_and_retrigger PASSED   [ 63%]
tests/test_monitoring.py::test_multiple_faces_threshold_and_reset PASSED [ 68%]
tests/test_monitoring.py::test_camera_failure_handling PASSED            [ 72%]
tests/test_pi_agent.py::test_pi_health_endpoint PASSED                   [ 77%]
tests/test_pi_agent.py::test_pi_auth_missing PASSED                      [ 81%]
tests/test_pi_agent.py::test_pi_auth_invalid PASSED                      [ 86%]
tests/test_pi_agent.py::test_pi_invalid_payload PASSED                   [ 90%]
tests/test_pi_agent.py::test_pi_valid_status_dry_run PASSED              [ 95%]
tests/test_pi_agent.py::test_pi_client_offline_graceful_handling PASSED  [100%]

============================== 22 passed in 3.61s ==============================
```

---

## 6. How to Inspect Events and Evidence

1. **Dashboard Interface**:
   - Scroll down to the **Flagged Event Log & Evidence Snapshots** table.
   - Click any snapshot thumbnail to open a high-resolution modal preview with event metadata.
2. **Database Queries**:
   Inspect the SQLite database directly:
   ```bash
   sqlite3 data/proctoring.db "SELECT id, timestamp, event_type, face_count, explanation FROM events;"
   ```
3. **Filesystem Snapshots**:
   Images are stored as standard JPEGs in `evidence/<event_id>.jpg`.
4. **Clearing Test Data**:
   Click **Clear Test Events** in the dashboard, or call the endpoint:
   ```bash
   curl -X POST http://127.0.0.1:5001/api/events/clear
   ```

---

## 7. Raspberry Pi 3 Model B Setup, Live Dashboard, & Hotspot Networking

The Raspberry Pi agent is located in `pi_agent/`. It runs an authenticated Flask server that receives proctoring events, hosts a dedicated **Live Status Dashboard** on port 5050, and actuates an optional visual status servo.

### Mobile Hotspot Configuration (Same LAN)
When your MacBook and Raspberry Pi are both connected to the same mobile hotspot:

1. **Find Pi's IP address on the hotspot**:
   On the Raspberry Pi terminal:
   ```bash
   hostname -I
   ```
   *(Example: `192.168.43.125`)*
2. **Start Pi Agent & Dashboard**:
   ```bash
   cd ~/exam_proctoring/pi_agent
   source venv/bin/activate
   export PI_SHARED_TOKEN="your_secure_shared_secret"
   export SERVO_ENABLED=false
   export SERVO_DRY_RUN=true
   python pi_server.py
   ```
3. **Open Pi Live Dashboard in Any Browser**:
   Navigate to: **`http://192.168.43.125:5050/`** (or `http://raspberrypi.local:5050/`)
   - Clean institutional white theme with zero emojis.
   - Real-time status badge (`NORMAL` / `ALERT`), candidate face count, and alert totals.
   - Servo motor position indicator (`-45°` Normal vs `+45°` Alert).
   - Live audit history table of all received notifications.

4. **Connect MacBook Proctoring Engine**:
   In your MacBook's `~/exam_proctoring/.env`:
   ```ini
   PI_ENABLED=true
   PI_BASE_URL=http://192.168.43.125:5050
   PI_SHARED_TOKEN=your_secure_shared_secret
   PI_TIMEOUT_SEC=2.0
   ```
   If the Pi is disconnected, powered off, or drops off Wi-Fi, **MacBook video proctoring continues uninterrupted**. The MacBook client uses non-blocking requests with a 2-second timeout and fails gracefully.

### Electrical Warning & Hardware Guardrails
> [!CAUTION]
> **DO NOT POWER THE SERVO MOTOR FROM THE RASPBERRY PI 5V OR 3.3V GPIO PINS.**
> - Servo motors draw high inductive stall currents (0.5A - 1.5A). Powering them from the Pi causes severe voltage sags, brownout resets, and SD card filesystem corruption.
> - **External Power**: Use a dedicated 5V regulated DC supply (at least 1.5A).
> - **Common Ground**: Connect the negative (-) terminal of the external supply to a Raspberry Pi Ground pin (e.g. Pin 6).
> - **Signal Wire**: Connect the servo signal line to **GPIO 18** (Physical Pin 12).

---

## 8. Troubleshooting Guide

| Issue | Root Cause | Solution |
|---|---|---|
| `Could not open camera` | macOS camera permission denied | Open **System Settings > Privacy & Security > Camera** and allow Terminal. |
| `Address already in use` | Port conflict (macOS AirPlay uses 5000) | The dashboard defaults to port **5001**. Set `DASHBOARD_PORT=5002` in `.env` if 5001 is busy. |
| Video stream is choppy or frozen | AVFoundation requested high 1080p stream | Keep resolution at `640x480` and `15 FPS` in `config.py`. |
| `AttributeError: module 'cv2' has no attribute 'CascadeClassifier'` | OpenCV 5.0.0 development pre-release installed | Reinstall pinned OpenCV: `pip install opencv-python==4.11.0.86`. |
| Pi health check fails / offline | Hostname resolution or firewall | Test with `curl http://<pi-ip-address>:5050/health`. Ensure both devices share the same local network. |
| Servo vibrates or fails to move | Floating ground or insufficient power | Verify external 5V power supply and confirm the Pi GND pin is tied to external power supply GND. |

---

## 9. Privacy, Ethical Monitoring, & Technical Boundaries

1. **Local-First Processing**: All computer vision inference and database operations happen strictly on `127.0.0.1`. No video frames or candidate biometric data are transmitted to external cloud APIs.
2. **Selective Evidence Only**: Continuous video recording is intentionally disabled. Snapshots are only saved when an event persists beyond configured thresholds.
3. **Head Pose vs. Eye Gaze**:
   - The current baseline uses Haar Cascades to detect face presence and count.
   - Future head-pose estimation estimates approximate rigid head angle (yaw/pitch).
   - **Gaze tracking** (detecting whether a candidate's eyes look at off-screen notes or a second display) is a fundamentally different and fragile task that standard webcams cannot perform reliably without eye-tracking hardware and calibrated infrared sensors. The system does not claim to track gaze direction.
4. **Data Retention**: Test data and snapshots can be removed with a single click using the "Clear Test Events" button or by clearing the `evidence/` directory.
