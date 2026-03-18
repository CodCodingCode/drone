"""
RC Controller via Arduino — fly the drone from your Mac.

Usage:
  python rc_control.py                  # keyboard control
  python rc_control.py --test           # sweep all channels to verify wiring
  python rc_control.py --port /dev/...  # specify serial port

Requires: rc_hack.ino flashed on Arduino Nano 33 BLE.
"""
import serial
import serial.tools.list_ports
import sys
import time
import threading
import argparse
import json
from datetime import datetime

SYNC = 0xAA
ACK = 0x55
CENTER = 128
CMD_HZ = 50  # send rate

class RCController:
    def __init__(self, port=None, baudrate=115200):
        if port is None:
            port = self._find_port()
        print(f"Connecting to Arduino on {port}...")
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        time.sleep(2)  # wait for Arduino reset
        self.ser.reset_input_buffer()

        # Stick state
        self.throttle = 0
        self.yaw = CENTER
        self.pitch = CENTER
        self.roll = CENTER

        self.running = True
        self.log = []
        self.sent = 0
        self.acked = 0

    def _find_port(self):
        """Auto-detect Arduino port."""
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            if "usbmodem" in p.device or "Arduino" in (p.description or ""):
                return p.device
        # Fallback
        for p in ports:
            if "usb" in p.device.lower():
                return p.device
        raise RuntimeError(
            f"No Arduino found. Available ports: {[p.device for p in ports]}"
        )

    def send(self):
        """Send current stick state to Arduino."""
        t = max(0, min(255, self.throttle))
        y = max(0, min(255, self.yaw))
        p = max(0, min(255, self.pitch))
        r = max(0, min(255, self.roll))
        pkt = bytes([SYNC, t, y, p, r])
        self.ser.write(pkt)
        self.sent += 1

        # Check for ACK
        resp = self.ser.read(1)
        if resp == bytes([ACK]):
            self.acked += 1

        self.log.append({
            "t": time.time(),
            "throttle": t, "yaw": y, "pitch": p, "roll": r,
            "ack": resp == bytes([ACK])
        })

    def send_loop(self):
        """Background thread sending at CMD_HZ."""
        interval = 1.0 / CMD_HZ
        while self.running:
            try:
                self.send()
            except Exception as e:
                print(f"  Serial error: {e}")
                break
            time.sleep(interval)

    def save_log(self):
        fname = f"rc_log_{int(time.time())}.json"
        with open(fname, "w") as f:
            json.dump(self.log, f)
        print(f"  Saved {len(self.log)} entries to {fname}")

    def disconnect(self):
        self.running = False
        # Safe state
        self.throttle = 0
        self.yaw = CENTER
        self.pitch = CENTER
        self.roll = CENTER
        try:
            self.send()
            self.send()
        except:
            pass
        self.ser.close()


def test_mode(rc):
    """Sweep each channel to verify wiring."""
    print("\n=== WIRING TEST MODE ===")
    print("Watch each channel sweep from min to max.\n")

    channels = [
        ("Throttle (D3 -> left stick vertical)", "throttle"),
        ("Yaw (D5 -> left stick horizontal)", "yaw"),
        ("Pitch (D6 -> right stick vertical)", "pitch"),
        ("Roll (D9 -> right stick horizontal)", "roll"),
    ]

    for name, attr in channels:
        print(f"Testing: {name}")
        # Sweep up
        for v in range(0, 256, 5):
            setattr(rc, attr, v)
            rc.send()
            time.sleep(0.02)
        # Sweep down
        for v in range(255, -1, -5):
            setattr(rc, attr, v)
            rc.send()
            time.sleep(0.02)
        # Return to center/zero
        setattr(rc, attr, 0 if attr == "throttle" else CENTER)
        rc.send()
        print(f"  Done. ACKs: {rc.acked}/{rc.sent}")
        time.sleep(0.5)

    print("\nAll channels tested. If a channel didn't move the")
    print("corresponding stick axis, check that wire.\n")


def keyboard_control(rc):
    """Interactive keyboard control."""
    # Start send loop
    t = threading.Thread(target=rc.send_loop, daemon=True)
    t.start()

    STEP = 20  # how much each keypress changes a value

    print("""
======================================================================
  RC CONTROL — Keyboard Mode
  Sending {hz}Hz to Arduino -> RC Controller -> Drone
======================================================================

  Throttle: {thr}  Yaw: {yaw}  Pitch: {pit}  Roll: {rol}

  Flight:   t=arm/takeoff (throttle to 180)
            l=land (throttle to 0)
            s=EMERGENCY STOP (all zero)
  Throttle: u=up  d=down
  Move:     w=forward  z=back (not 's'!)
            a=left  f=right (not 'd'!)
  Yaw:      j=rotate left  k=rotate right
  Other:    c=center all  p=print state  x=save log  q=quit
""".format(hz=CMD_HZ, thr=rc.throttle, yaw=rc.yaw, pit=rc.pitch, rol=rc.roll))

    while rc.running:
        try:
            cmd = input("> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if not cmd:
            continue

        if cmd == "t":
            rc.throttle = 180
            print("  ARM/TAKEOFF (throttle=180)")
        elif cmd == "l":
            # Gradual descent
            print("  LANDING...")
            for v in range(rc.throttle, -1, -5):
                rc.throttle = v
                time.sleep(0.05)
            print("  Landed (throttle=0)")
        elif cmd == "s":
            rc.throttle = 0
            rc.yaw = CENTER
            rc.pitch = CENTER
            rc.roll = CENTER
            print("  EMERGENCY STOP")
        elif cmd == "u":
            rc.throttle = min(255, rc.throttle + STEP)
            print(f"  Throttle UP: {rc.throttle}")
        elif cmd == "d":
            rc.throttle = max(0, rc.throttle - STEP)
            print(f"  Throttle DOWN: {rc.throttle}")
        elif cmd == "w":
            rc.pitch = CENTER + 60  # forward
            print(f"  Pitch FORWARD: {rc.pitch}")
        elif cmd == "z":
            rc.pitch = CENTER - 60  # back
            print(f"  Pitch BACK: {rc.pitch}")
        elif cmd == "a":
            rc.roll = CENTER - 60
            print(f"  Roll LEFT: {rc.roll}")
        elif cmd == "f":
            rc.roll = CENTER + 60
            print(f"  Roll RIGHT: {rc.roll}")
        elif cmd == "j":
            rc.yaw = CENTER - 60
            print(f"  Yaw LEFT: {rc.yaw}")
        elif cmd == "k":
            rc.yaw = CENTER + 60
            print(f"  Yaw RIGHT: {rc.yaw}")
        elif cmd == "c":
            rc.throttle = 0
            rc.yaw = CENTER
            rc.pitch = CENTER
            rc.roll = CENTER
            print("  Centered all sticks")
        elif cmd == "p":
            print(f"  T={rc.throttle} Y={rc.yaw} P={rc.pitch} R={rc.roll}")
            print(f"  Sent: {rc.sent}  ACKs: {rc.acked}")
        elif cmd == "x":
            rc.save_log()
        elif cmd == "q":
            break
        else:
            # Release direction sticks after any unrecognized input
            rc.pitch = CENTER
            rc.roll = CENTER
            rc.yaw = CENTER


def main():
    parser = argparse.ArgumentParser(description="RC drone control via Arduino")
    parser.add_argument("--port", help="Serial port (auto-detected if omitted)")
    parser.add_argument("--test", action="store_true", help="Run wiring test sweep")
    args = parser.parse_args()

    rc = RCController(port=args.port)
    print(f"  Connected! ACK test: ", end="")
    rc.send()
    print(f"{'OK' if rc.acked else 'no ACK (check sketch is flashed)'}")

    try:
        if args.test:
            test_mode(rc)
        else:
            keyboard_control(rc)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  Shutting down (safe state)...")
        rc.disconnect()
        rc.save_log()
        print("  Done.")


if __name__ == "__main__":
    main()
