# Raspberry Pi 3 Model B - Exam Proctoring Hardware Agent & Live Dashboard

This sub-project runs on a **Raspberry Pi 3 Model B** to:
1. Receive authenticated status notifications from the MacBook computer vision engine over HTTP.
2. Host an institutional, browser-based **Live Status Dashboard** on port 5050.
3. Actuate an optional indicator servo motor (safe dry-run mode enabled by default).

---

## 1. Safety & Electrical Warning (READ BEFORE CONNECTING HARDWARE)

> [!CAUTION]
> **NEVER POWER A SERVO MOTOR DIRECTLY FROM THE RASPBERRY PI 5V OR 3.3V GPIO HEADER PINS.**
>
> 1. **Current Spikes & Brownouts**: Even a small micro-servo (e.g. SG90) draws 500 mA to 1000 mA during movement or stall. The Raspberry Pi 3B 5V rail cannot safely supply inductive motor spikes, causing instantaneous voltage drops, kernel panics, and SD card filesystem corruption.
> 2. **Back-EMF Danger**: Inductive motor kickback can backfeed into the 3.3V Broadcom processor rails, permanently destroying the GPIO multiplexer.
> 3. **Common Ground is Mandatory**: When using an external power source, the ground (GND) of the external power supply MUST be connected to the Raspberry Pi GND pin. Without a shared common ground, the PWM signal reference floats, resulting in violent motor jitter or failure to trigger.

---

## 2. Proposed Wiring Diagram

| Servo Wire Color | Function | Connection Point |
|---|---|---|
| **Brown / Black** | Ground (GND) | Connect to **BOTH** External Power Supply GND **AND** Raspberry Pi GND (Pin 6 or 14) |
| **Red** | Power (VCC +5V) | Connect **ONLY** to External 5V Regulated Power Supply Positive (+) |
| **Orange / Yellow / White** | PWM Signal | Connect to **Raspberry Pi GPIO 18** (Physical Header Pin 12) |

```
    [ External 5V / 2A Power Supply ]
           (+) -------------> Red Wire (Servo VCC)
           (-) -----+-------> Brown/Black Wire (Servo GND)
                    |
                    | (Common Ground Reference)
                    v
    [ Raspberry Pi 3 Model B ]
       Pin 6 (GND) -+
       Pin 12 (BCM GPIO 18) -> Orange/Yellow Wire (Servo Signal)
```

---

## 3. Connecting MacBook & Raspberry Pi via Mobile Hotspot

When your MacBook and Raspberry Pi are both connected to the same mobile hotspot:

### Step 1: Find the Raspberry Pi's IP Address
On your Raspberry Pi terminal (via display or SSH):
```bash
hostname -I
```
*(Example output: `192.168.43.125`)*

Alternatively, view connected devices inside your phone's Mobile Hotspot settings, or on your MacBook run:
```bash
arp -a
# or
ping raspberrypi.local
```

### Step 2: Configure Environment on the Raspberry Pi
On the Raspberry Pi:
```bash
cd ~/exam_proctoring/pi_agent   # or your deployed folder
source venv/bin/activate

export PI_SHARED_TOKEN="your_secure_shared_secret"
export SERVO_ENABLED=false
export SERVO_DRY_RUN=true
export PI_PORT=5050
export PI_HOST=0.0.0.0

python pi_server.py
```

The Pi server will start:
```
[INFO] [PiAgent] Starting Raspberry Pi Proctoring Agent on 0.0.0.0:5050
Servo Enabled: False | Dry Run Mode: True | Pin: GPIO18
```

### Step 3: Configure `.env` on your MacBook
In your MacBook's `~/exam_proctoring/.env` file:
```ini
PI_ENABLED=true
PI_BASE_URL=http://192.168.43.125:5050
PI_SHARED_TOKEN=your_secure_shared_secret
PI_TIMEOUT_SEC=2.0
```
*(Replace `192.168.43.125` with your Pi's actual hotspot IP).*

---

## 4. Live Multi-Workstation Command Center on Raspberry Pi

The Raspberry Pi serves an institutional, real-time command center:

👉 **`http://<RASPBERRY_PI_IP>:5050/`** (e.g. `http://172.20.10.2:5050/`)

### Command Center Features:
- **Professional Command Center Dark Theme**: Refined high-contrast dark palette (`#090d16` / `#0f172a`), Inter and JetBrains Mono typography, glowing status dots, zero clutter.
- **Audible & Visual Alert Engine**: Dual-tone synthesized alarm chimes (Web Audio API) when any student triggers an alert, accompanied by an animated sliding banner with direct triage buttons.
- **Candidate Snapshot Ingestion**: Receives synchronized JPEG incident snapshots directly from student laptops and displays candidate photos on workstation cards and in dossier previews.
- **Workstation Grid & Candidate Dossiers**: Displays live status of every workstation (`DESK-01`, `DESK-02`, etc.), face counts, alert durations, IP addresses, and ping latency.
- **Proctor Controls**: One-click "Acknowledge Alert" (per desk or hall-wide), "Prune Offline Desks", "Simulate Exam Hall (4 Desks)", and "Export Report" (JSON/CSV).
- **Servo Indicator & Needle Gauge**: Real-time physical indicator needle showing -45° Nominal, 0° Idle, and +45° Alert with GPIO pin tracking.

---

## 5. Endpoints Reference

| Endpoint | Method | Auth Required | Purpose |
|---|---|---|---|
| `/` | GET | No | Real Exam Proctoring Command Center UI |
| `/health` | GET | No | Liveness probe for student laptop clients |
| `/api/status` | GET | No | Real-time JSON telemetry for browser polling |
| `/status` | POST | **Yes** (Bearer) | Receives candidate status, face count & optional snapshot |
| `/api/workstation/<id>/acknowledge` | POST | **Yes** | Acknowledges alert for a specific workstation |
| `/api/acknowledge_all` | POST | **Yes** | Acknowledges all active alerts in the hall |
| `/api/export_report` | GET | No | Downloads complete session audit report (JSON) |
| `/api/simulate_multi` | POST | **Yes** | Populates 4 simulated candidate stations for demo |
| `/test_servo` | POST | **Yes** (Bearer) | Manually triggers test servo movement |
| `/api/clear_inactive` | POST | **Yes** (Bearer) | Prunes offline workstations |
| `/api/clear_history` | POST | **Yes** (Bearer) | Resets in-memory event history |

---

## 6. Running Multiple Student Workstations to One Pi

Each student laptop runs the client proctoring service pointing to the singular Raspberry Pi:

### Student Laptop 1 (Desk 01 - Native Camera):
```bash
python run.py --device-id DESK-01 --candidate-name "Alice Smith" --camera native --pi-url http://172.20.10.2:5050
```

### Student Laptop 2 (Desk 02 - External USB Camera):
```bash
python run.py --device-id DESK-02 --candidate-name "Bob Jones" --camera external --pi-url http://172.20.10.2:5050
```

### Student Laptop 3 (Desk 03 - Auto-detect Camera):
```bash
python run.py --device-id DESK-03 --candidate-name "Charlie Davis" --camera auto --pi-url http://172.20.10.2:5050
```

---

## 7. Enabling Physical Hardware (Advanced)

Only enable after completing the electrical verification checklist in Section 1:
```bash
export PI_SHARED_TOKEN="your_secure_shared_secret"
export SERVO_ENABLED=true
export SERVO_DRY_RUN=false
export SERVO_PIN=18

python pi_server.py
```
