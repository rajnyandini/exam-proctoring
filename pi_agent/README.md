# Raspberry Pi 3 Model B - Exam Proctoring Hardware Agent

This sub-project runs on a **Raspberry Pi 3 Model B** to receive authenticated status updates from the MacBook proctoring computer vision engine and actuate an optional indicator servo motor.

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

## 3. Servo Identification Checklist

Before toggling `SERVO_ENABLED=true`:
1. **Identify the exact model stamped on the servo** (e.g. TowerPro SG90, MG90S, DS3218).
2. **Consult manufacturer datasheet**:
   - Operating Voltage: typically 4.8V – 6.0V.
   - Operating Frequency: standard analog servos use 50 Hz (20 ms period).
   - Pulse Range: standard conservative is 1.0 ms (-45°/0°) to 2.0 ms (+45°/90°).
   - Stall Current: ensure your external supply provides at least 1.5A per motor.

---

## 4. Raspberry Pi Software Installation

### Step A: Flash Raspberry Pi OS Lite
Use the official Raspberry Pi Imager to flash **Raspberry Pi OS Lite (64-bit or 32-bit)** to a microSD card.
In the Imager settings gear:
- Set hostname: `raspberrypi.local`
- Enable SSH with password or public key
- Configure Wi-Fi credentials (or connect via Ethernet)

### Step B: Connect via SSH
From your MacBook terminal:
```bash
ssh pi@raspberrypi.local
```

### Step C: Deploy Pi Agent Code
Copy `pi_agent/` files to the Pi, or clone the project:
```bash
mkdir -p ~/proctor_agent
cd ~/proctor_agent
```

Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install flask
```

*(Optional: Install hardware GPIO libraries only once wiring is verified):*
```bash
pip install gpiozero pigpio
```

---

## 5. Running in Safe Dry-Run Mode (Default)

The agent defaults to **DRY-RUN mode**. No physical electrical signals are pulsed:

```bash
export PI_SHARED_TOKEN="your_secure_shared_secret_here"
export SERVO_ENABLED=false
export SERVO_DRY_RUN=true
export PI_PORT=5050

python pi_server.py
```

### Verification from MacBook
Test the health endpoint from your MacBook:
```bash
curl -i http://raspberrypi.local:5050/health
```

Expected response:
```json
{
  "auth_configured": true,
  "current_indicator_state": "IDLE",
  "device": "Raspberry Pi 3 Model B Agent",
  "dry_run": true,
  "servo_enabled": false,
  "servo_pin": 18,
  "status": "online"
}
```

Test authenticated status update:
```bash
curl -i -X POST http://raspberrypi.local:5050/status \
  -H "Authorization: Bearer your_secure_shared_secret_here" \
  -H "Content-Type: application/json" \
  -d '{"status": "ALERT", "event_type": "FACE_ABSENT", "face_count": 0, "explanation": "Test alert"}'
```

The Pi console will print:
`[DRY-RUN SIMULATION] Would actuate servo on GPIO18 to position ALERT (approx angle: 45 deg). Physical actuation is DISABLED.`

---

## 6. Enabling Physical Hardware (Advanced)

Only enable after completing Section 1 & 2:
```bash
export PI_SHARED_TOKEN="your_secure_shared_secret_here"
export SERVO_ENABLED=true
export SERVO_DRY_RUN=false
export SERVO_PIN=18

python pi_server.py
```
