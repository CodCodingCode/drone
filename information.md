# TY-T6 Drone VLA — Natural Language to Physical Action

> A project to collect paired (vision, language, action) data from a TYH TY-T6 WiFi drone, fine-tune an open-source VLA model, and deploy it so the drone responds to natural language commands.

---

## Project Goal

Build a minimal end-to-end VLA (Vision-Language-Action) pipeline on cheap consumer hardware. The drone receives a natural language command ("fly forward", "turn left", "land"), observes its environment through its front-facing camera, and outputs the correct UDP control packet.

This is a learning project to understand the full VLA data pipeline — from raw sensor collection through training to deployment — in preparation for building developer tooling for VLAs (think: Roboflow, but for physical robot policies).

---

## Hardware

| Component    | Details                                    |
| ------------ | ------------------------------------------ |
| Drone        | TYH TY-T6 WiFi FPV Quadcopter              |
| Camera       | Front-facing 2MP WiFi camera               |
| Control      | UDP over WiFi (drone acts as AP)           |
| Video        | WiFi video stream via TYH Fly app protocol |
| Drone IP     | `192.168.0.1` (default)                    |
| Control Port | `8800` (UDP)                               |

**What the drone has:**

- Built-in altitude hold (barometer)
- 6-axis gyroscope (internal only, not broadcast)
- WiFi hotspot
- Front camera stream

**What the drone does NOT have:**

- GPS
- Optical flow
- Telemetry output (no state data over WiFi)
- IMU broadcast

---

## System Architecture

```
Natural Language Command
        │
        ▼
  Language Encoder (CLIP / distilBERT)
        │
        ▼
  ┌─────────────────────────┐
  │  Camera Frame (live)    │──► Vision Encoder (ViT / MobileNet)
  └─────────────────────────┘
        │
        ▼
   Action Head
        │
        ▼
  UDP Packet [roll, pitch, throttle, yaw]
        │
        ▼
  TY-T6 Drone
```

---

## Phase 1 — Setup & Connection

### Step 1: Connect to the drone

1. Power on the TY-T6, place on flat surface
2. Connect laptop WiFi to drone hotspot (`TYH_XXXX` or `WIFI_UAV_XXXX`)
3. Verify connection: `ping 192.168.0.1`

### Step 2: Verify protocol with Wireshark

1. Download Wireshark from wireshark.org
2. Open Wireshark, select WiFi interface, start capture
3. Filter: `udp`
4. Open TYH Fly app on phone, move joysticks
5. Observe UDP packets changing — map bytes to controls
6. Note: port 8800 for control, video stream on separate port

### Step 3: Basic Python control test

```python
import socket
import time

DRONE_IP = "192.168.0.1"
CONTROL_PORT = 8800

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_command(roll=0x80, pitch=0x80, throttle=0x80, yaw=0x80):
    packet = bytearray(19)
    packet[0] = 0x66
    packet[1] = roll
    packet[2] = pitch
    packet[3] = throttle
    packet[4] = yaw
    packet[18] = 0x99
    sock.sendto(bytes(packet), (DRONE_IP, CONTROL_PORT))

# Start video stream
sock.sendto(bytes([0xef, 0x00, 0x04, 0x00]), (DRONE_IP, CONTROL_PORT))

# Hover (all neutral)
send_command()
```

**Reference repo:** [heidtn/py_wifi_drone](https://github.com/heidtn/py_wifi_drone) — confirmed working on TYH/FQ777 firmware family.

---

## Phase 2 — Data Collection

### What to collect

Every timestep (every ~100ms), record:

```json
{
  "timestamp": 1234567890.123,
  "image": "<base64 or filepath to frame>",
  "command": "fly forward",
  "action": [128, 170, 128, 128]
}
```

### Data collection script (skeleton)

```python
import socket
import cv2
import json
import time
import threading

DRONE_IP = "192.168.0.1"
CONTROL_PORT = 8800
VIDEO_PORT = 8888  # confirm with Wireshark

dataset = []
current_command = "hover"

def capture_video():
    cap = cv2.VideoCapture(f"udp://{DRONE_IP}:{VIDEO_PORT}")
    while True:
        ret, frame = cap.read()
        if ret:
            yield frame

def log_datapoint(frame, command, action):
    dataset.append({
        "timestamp": time.time(),
        "image": frame,  # save to disk in practice
        "command": command,
        "action": list(action)
    })

def send_and_log(command, roll=0x80, pitch=0x80, throttle=0x80, yaw=0x80):
    action = [roll, pitch, throttle, yaw]
    # send UDP packet
    packet = bytearray(19)
    packet[1], packet[2], packet[3], packet[4] = action
    sock.sendto(bytes(packet), (DRONE_IP, CONTROL_PORT))
    # log it
    log_datapoint(current_frame, command, action)
```

### Commands to collect data for

| Command      | Roll | Pitch | Throttle | Yaw  |
| ------------ | ---- | ----- | -------- | ---- |
| hover        | 0x80 | 0x80  | 0x80     | 0x80 |
| fly forward  | 0x80 | 0xAA  | 0x80     | 0x80 |
| fly backward | 0x80 | 0x55  | 0x80     | 0x80 |
| turn left    | 0x80 | 0x80  | 0x80     | 0x55 |
| turn right   | 0x80 | 0x80  | 0x80     | 0xAA |
| go up        | 0x80 | 0x80  | 0xAA     | 0x80 |
| land         | 0x80 | 0x80  | 0x30     | 0x80 |

---

## Phase 3 — Dataset Formatting

### HuggingFace dataset format

```python
from datasets import Dataset
from PIL import Image

data = {
    "image": [Image.open(f) for f in image_files],
    "text": commands,
    "action": actions  # list of [roll, pitch, throttle, yaw]
}

dataset = Dataset.from_dict(data)
dataset.push_to_hub("your-username/ty-t6-drone-vla")
```

---

## Phase 4 — Model Training

### Option A: LeRobot (recommended)

HuggingFace's own robotics framework — designed exactly for this pipeline.

```bash
pip install lerobot
```

- Supports (image, language) → action training out of the box
- Active HuggingFace team behind it
- Docs: huggingface.co/lerobot

### Option B: OpenVLA

Open-source VLA model on HuggingFace. Fine-tune on your dataset:

```python
from transformers import AutoModelForVision2Seq, AutoProcessor

model = AutoModelForVision2Seq.from_pretrained("openvla/openvla-7b")
processor = AutoProcessor.from_pretrained("openvla/openvla-7b")
```

### Input/Output spec

|                | Type        | Shape                        |
| -------------- | ----------- | ---------------------------- |
| Input: image   | RGB frame   | (224, 224, 3)                |
| Input: text    | string      | "fly forward"                |
| Output: action | float array | [roll, pitch, throttle, yaw] |

---

## Phase 5 — Deployment

### Inference loop

```python
import torch
from PIL import Image

def fly_with_command(command: str):
    while True:
        # grab live frame
        frame = get_current_frame()

        # run model
        inputs = processor(images=frame, text=command, return_tensors="pt")
        with torch.no_grad():
            action = model.generate(**inputs)

        roll, pitch, throttle, yaw = decode_action(action)

        # send to drone
        send_command(roll, pitch, throttle, yaw)

        time.sleep(0.1)  # 10Hz control loop

fly_with_command("fly forward slowly")
```

---

## Known Limitations

| Limitation                  | Impact                                            |
| --------------------------- | ------------------------------------------------- |
| No telemetry from drone     | Model is open-loop — can't confirm actions worked |
| No GPS / optical flow       | No position or velocity feedback                  |
| Short battery life (~8 min) | Limited data collection window per session        |
| Noisy video stream          | Frame artifacts may affect vision encoder         |
| Indoor only                 | Wind and lighting variation not captured          |

---

## Broader Purpose

This project is a hands-on way to understand every layer of the VLA stack:

1. **Data collection** — the hardest unsolved problem in robotics
2. **Data formatting** — pairing vision, language, and action at the right timestamps
3. **Model training** — fine-tuning foundation models on robot data
4. **Deployment** — closing the loop from model output to physical action

The insight this builds directly towards: building **Roboflow for VLAs** — developer tooling that makes the above pipeline easy, standardized, and accessible for any robot.

---

## References

- [heidtn/py_wifi_drone](https://github.com/heidtn/py_wifi_drone) — Python control for TYH/FQ777 WiFi drones
- [FahrulRPutra/reversing-wifi-uav](https://github.com/FahrulRPutra/reversing-wifi-uav) — WiFi UAV protocol reverse engineering
- [HuggingFace LeRobot](https://huggingface.co/lerobot) — robotics training framework
- [OpenVLA](https://huggingface.co/openvla/openvla-7b) — open source VLA model
- [Physical Intelligence π0](https://physicalintelligence.company/blog/pi0) — reference architecture
