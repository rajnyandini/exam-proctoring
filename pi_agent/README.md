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

## 4. Live Browser Dashboard on the Raspberry Pi

The Raspberry Pi serves an independent, real-time live monitoring dashboard:

👉 **`http://<RASPBERRY_PI_IP>:5050/`** (e.g. `http://192.168.43.125:5050/`)

### Dashboard Features:
- **Clean Institutional Theme**: Consistent white and slate palette, zero emojis, high-contrast typography.
- **Hero Status Banner**: Displays live proctoring state (`NORMAL` in green, `ALERT` in crimson, or `AWAITING CONNECTION` in slate).
- **Servo Indicator**: Shows current indicator position (`Normal (-45°)` vs `Alert (+45°)`) and hardware mode (`Dry-Run Simulation` vs `Physical Active`).
- **Telemetry Tiles**: Face count, active anomaly type, alert counter, and seconds since last update.
- **Audit Table**: Shows received status updates with timestamps and proctor explanation notes.

---

## 5. Endpoints Reference

| Endpoint | Method | Auth Required | Purpose |
|---|---|---|---|
| `/` | GET | No | Live Status Web Dashboard |
| `/health` | GET | No | Liveness probe for MacBook client |
| `/api/status` | GET | No | Real-time JSON telemetry for browser polling |
| `/status` | POST | **Yes** (Bearer) | Receives proctoring status and actuates servo |
| `/test_servo` | POST | **Yes** (Bearer) | Manually triggers test servo movement |
| `/api/clear_history` | POST | **Yes** (Bearer) | Resets in-memory event history |

---

## 6. Testing Communication from MacBook

### Health Check:
```bash
curl -s http://192.168.43.125:5050/health
```

### Send Authenticated Status:
```bash
curl -X POST http://192.168.43.125:5050/status \
  -H "Authorization: Bearer your_secure_shared_secret" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "ALERT",
    "event_type": "FACE_ABSENT",
    "face_count": 0,
    "explanation": "Candidate absent from camera frame for 5.0 seconds."
  }'
```

The Pi dashboard at `http://192.168.43.125:5050/` will instantly update to show `ALERT`, update the telemetry, and record the entry in the table.

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
