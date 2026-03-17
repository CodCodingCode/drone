# TY-T6 UART Hardware Mod — WiFi Flight Control

## What We're Doing

The Lewei camera module talks to the flight controller (FC) over a serial UART line at 115200 baud. We're going to:

1. Open the drone
2. Find the UART lines between camera module and FC
3. Tap into them with a USB-to-serial adapter (to sniff the protocol)
4. Then inject our own commands (to control flight from the Mac)

```
                    BEFORE:
RC Controller ─── 2.4GHz ───→ Flight Controller ← UART → Camera Module ← WiFi → Phone

                    AFTER:
RC Controller ─── 2.4GHz ───→ Flight Controller ← UART → Camera Module ← WiFi → Mac
                                      ↑
                                 UART tap
                                      ↑
                              USB-Serial Adapter
                                      ↑
                                    Mac
                                (our Python script)
```

---

## What You Need to Buy

| Item | Price | Where |
|------|-------|-------|
| USB-to-UART adapter (CP2102 or FTDI) | ~$6 | Amazon: "CP2102 USB to TTL" |
| Dupont jumper wires (female-female) | ~$5 | Amazon: "dupont jumper wire" |
| Soldering iron + solder (if needed) | ~$15 | Amazon (or borrow) |
| Multimeter (to find lines) | ~$10 | Amazon (cheap one is fine) |

**Total: ~$20-35** (you may already have some of this)

Optional but helpful:
- Logic analyzer ($10, "Saleae clone 8ch") — to decode the protocol cleanly
- Magnifying glass / helping hands — the wires are small

---

## Step 1: Open the Drone

1. Remove the 4 propellers (pull straight up)
2. Flip drone over, find screws (usually 4-6 Phillips head screws)
3. Carefully separate top and bottom shell
4. You'll see two PCBs:
   - **Camera module** (has the camera lens, WiFi antenna, usually marked LW9621 or similar)
   - **Flight controller** (has the gyro chip, motor driver, connected to 4 motors)
5. Find the ribbon cable or wires connecting them — that's the UART link

---

## Step 2: Identify the UART Lines

The UART connection between camera and FC typically has 4 wires:

| Wire | Purpose |
|------|---------|
| VCC  | Power (3.3V usually) |
| GND  | Ground |
| TX   | Camera → FC (camera sending to FC) |
| RX   | FC → Camera (FC sending to camera) |

### How to find them:

**Method A: Visual inspection**
- Look for labeled pads on either PCB: TX, RX, GND, VCC, or UART
- Often near the connector between the two boards
- The Lewei LW9621 datasheet shows UART pins if you can read the chip markings

**Method B: Multimeter**
1. Set multimeter to continuity/beep mode
2. Find GND: touch one probe to battery negative, other to each pin — beep = GND
3. Find VCC: switch to voltage mode, power on drone, measure each pin vs GND — 3.3V = VCC
4. TX/RX: the remaining two wires. TX from camera will show voltage fluctuations when camera is active

**Method C: Logic analyzer (cleanest)**
1. Connect GND from analyzer to drone GND
2. Clip each of the remaining wires to an analyzer channel
3. Power on drone
4. Look for 115200 baud serial data on your logic analyzer software (PulseView is free)

---

## Step 3: Sniff the Protocol

Before injecting commands, we need to see what the RC controller's commands look like when they arrive at the FC.

### Wiring (to sniff):

```
Camera Module                Flight Controller
    TX ──────────────────────── RX
    RX ──────────────────────── TX
    GND ─────────────────────── GND

         ┌── Tap here (don't cut!)
         │
    USB-Serial Adapter:
         RX ← connect to FC's RX line (to see commands going TO the FC)
         GND ← connect to drone GND
         (leave adapter TX disconnected for now)
```

**IMPORTANT: DO NOT connect VCC from the USB adapter to the drone. Only connect GND and RX.**

### Sniff script:

```bash
# Find your USB-serial adapter
ls /dev/tty.usb*
# or
ls /dev/cu.usb*

# Sniff at 115200 baud
python uart_sniff.py /dev/tty.usbserial-0001
```

---

## Step 4: Decode the FC Protocol

With the sniff running:
1. Power on the drone + RC controller
2. Move the RC sticks
3. Watch the serial data — you'll see the actual command bytes
4. The uart_sniff.py script will log everything and do byte analysis

Common patterns for cheap FC serial protocols:
- Header byte (0x55, 0xAA, 0x66, etc.)
- Channel data (4 bytes for roll/pitch/throttle/yaw)
- Flags (arm, disarm, mode)
- Checksum
- Footer byte

---

## Step 5: Inject Commands

Once we know the protocol, we wire in to SEND:

```
Camera Module                Flight Controller
    TX ──────────────────────── RX  ← we cut this line
    RX ──────────────────────── TX

    USB-Serial Adapter:
         TX ──→ FC's RX (we now control what the FC receives)
         RX ←── FC's TX (optional: read telemetry if any)
         GND ── drone GND
```

**Option A: Cut the camera→FC TX line, replace with our commands**
- Pro: full control
- Con: camera module can't talk to FC anymore (usually fine, it's just status)

**Option B: Use a multiplexer / tri-state buffer**
- Pro: can switch between RC and Mac control
- Con: more complex wiring

Then run the injection script from the Mac over USB-serial.

---

## Safety Notes

- **Always test with propellers removed first** — motors WILL spin
- The FC board runs at 3.3V logic — the CP2102 adapter supports 3.3V (make sure yours does!)
- If using a 5V adapter, you NEED a level shifter or you'll fry the FC
- Keep the battery disconnected while soldering
- Take photos of everything before you modify it
