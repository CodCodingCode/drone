"""
Test undocumented lewei commands 65 and 100 for flight control.

CMD 100 responded to a body containing flight data and returned 8 bytes.
This could be a UART passthrough to the FC.

Run: python lewei_flight_test.py

PUT DRONE ON FLAT SURFACE, PROPELLERS OFF FOR FIRST TEST.
If motors twitch/spin on any test, we found it.
"""
import socket
import struct
import time
import json
import sys
import threading

DRONE_IP = "192.168.0.1"
CMD_PORT = 8060
MAGIC = b'lewei_cmd\x00'
CENTER = 0x80


def send_lewei(cmd_id, arg1=0, body=b"", timeout=1):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((DRONE_IP, CMD_PORT))
        hdr = struct.pack('<9I', cmd_id, arg1, 0, len(body), 0, 0, 0, 0, 0)
        s.sendall(MAGIC + hdr + body)
        try:
            resp = s.recv(4096)
            s.close()
            return resp
        except socket.timeout:
            s.close()
            return None
    except Exception:
        return None


def send_lewei_persistent(sock, cmd_id, arg1=0, body=b""):
    """Send on an already-open socket (for rapid fire commands)."""
    hdr = struct.pack('<9I', cmd_id, arg1, 0, len(body), 0, 0, 0, 0, 0)
    sock.sendall(MAGIC + hdr + body)


def make_flight_body_A(roll=CENTER, pitch=CENTER, throttle=CENTER, yaw=CENTER, cmd=0):
    """19-byte 0x66..0x99 format."""
    pkt = bytearray(19)
    pkt[0] = 0x66
    pkt[1] = roll
    pkt[2] = pitch
    pkt[3] = throttle
    pkt[4] = yaw
    pkt[5] = cmd
    pkt[18] = 0x99
    return bytes(pkt)


def make_flight_body_raw(roll=CENTER, pitch=CENTER, throttle=CENTER, yaw=CENTER, cmd=0):
    """Raw 4-byte stick values + command, no framing."""
    return bytes([roll, pitch, throttle, yaw, cmd])


def make_flight_body_B(roll=CENTER, pitch=CENTER, throttle=CENTER, yaw=CENTER, cmd=0):
    """8-byte 0xCC..0x33 format."""
    pkt = bytearray(8)
    pkt[0] = 0xCC
    pkt[1] = roll
    pkt[2] = pitch
    pkt[3] = throttle
    pkt[4] = yaw
    pkt[5] = cmd
    pkt[6] = (roll ^ pitch ^ throttle ^ yaw ^ cmd) & 0xFF
    pkt[7] = 0x33
    return bytes(pkt)


if __name__ == "__main__":
    print("=" * 60)
    print("  LEWEI FLIGHT CONTROL TEST")
    print("  Testing CMD 65 and CMD 100 with flight data")
    print("=" * 60)
    print()
    print("  !!! REMOVE PROPELLERS FOR FIRST TEST !!!")
    print("  Watch/listen for motor activity.")
    print()

    log = []

    def try_cmd(cmd_id, arg1, body, desc):
        resp = send_lewei(cmd_id, arg1, body)
        status = "RESPONDED" if resp else "no response"
        resp_hex = resp.hex() if resp else ""
        log.append({"cmd": cmd_id, "arg1": arg1, "body": body.hex(), "desc": desc,
                     "response": resp_hex, "responded": resp is not None})
        # Check if response changed from baseline
        print(f"  cmd={cmd_id:3d} arg1={arg1:6d} body={body.hex()[:40]:40s} | {status}")
        if resp:
            # Parse response body
            if len(resp) >= 46:
                resp_body = resp[46:]
                if resp_body:
                    print(f"    response body: {resp_body.hex()}")
        return resp

    # ── Test 1: CMD 100 baseline ──
    print("\n[1] CMD 100 — baseline (no body)")
    try_cmd(100, 0, b"", "baseline no body")

    print("\n[2] CMD 100 — with flight bodies (idle)")
    try_cmd(100, 0, make_flight_body_A(), "19byte idle")
    try_cmd(100, 0, make_flight_body_B(), "8byte idle")
    try_cmd(100, 0, make_flight_body_raw(), "raw idle")

    print("\n[3] CMD 100 — TAKEOFF commands")
    try_cmd(100, 0, make_flight_body_A(cmd=1), "19byte takeoff")
    try_cmd(100, 0, make_flight_body_A(cmd=1, throttle=0xFF), "19byte takeoff+maxthrottle")
    try_cmd(100, 0, make_flight_body_B(cmd=1), "8byte takeoff")
    try_cmd(100, 0, make_flight_body_raw(cmd=1, throttle=0xFF), "raw takeoff+maxthrottle")
    try_cmd(100, 1, make_flight_body_A(), "19byte idle arg1=1")
    try_cmd(100, 1, b"", "empty body arg1=1(takeoff?)")
    try_cmd(100, 2, b"", "empty body arg1=2(land?)")
    try_cmd(100, 4, b"", "empty body arg1=4(stop?)")

    print("\n[4] CMD 100 — different arg1 values")
    for a in [0, 1, 2, 3, 4, 8, 16, 32, 64, 128, 255, 256, 512, 1024]:
        try_cmd(100, a, make_flight_body_A(cmd=1, throttle=0xAA), f"takeoff arg1={a}")

    # ── Test 5: CMD 65 ──
    print("\n[5] CMD 65 — baseline")
    try_cmd(65, 0, b"", "baseline")
    try_cmd(65, 0, make_flight_body_A(), "19byte idle")
    try_cmd(65, 0, make_flight_body_A(cmd=1), "19byte takeoff")
    try_cmd(65, 0, make_flight_body_A(cmd=1, throttle=0xFF), "19byte takeoff+maxthrottle")
    try_cmd(65, 1, b"", "arg1=1")
    try_cmd(65, 1, make_flight_body_A(cmd=1), "19byte takeoff arg1=1")

    for a in [0, 1, 2, 4, 8, 255]:
        try_cmd(65, a, make_flight_body_raw(cmd=1, throttle=0xFF), f"raw takeoff arg1={a}")

    # ── Test 6: Try other unknown command IDs near 65 and 100 ──
    print("\n[6] Scanning nearby command IDs (60-70, 95-110)")
    for cmd_id in list(range(60, 71)) + list(range(95, 111)):
        try_cmd(cmd_id, 0, make_flight_body_A(cmd=1, throttle=0xAA), f"scan cmd={cmd_id}")

    # ── Test 7: Rapid fire on persistent connection ──
    print("\n[7] Rapid fire CMD 100 — 20Hz for 3 seconds (like real controller)")
    print("  WATCH THE MOTORS!")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((DRONE_IP, CMD_PORT))
        s.settimeout(1)

        start = time.time()
        count = 0
        while time.time() - start < 3:
            body = make_flight_body_A(throttle=0xAA, cmd=1)
            try:
                send_lewei_persistent(s, 100, 0, body)
                count += 1
            except BrokenPipeError:
                print("  Connection broken during rapid fire")
                break
            time.sleep(0.05)

        # Check for response
        s.settimeout(0.5)
        try:
            resp = s.recv(4096)
            print(f"  Got {len(resp)} bytes back after rapid fire: {resp.hex()[:80]}")
        except socket.timeout:
            pass
        s.close()
        print(f"  Sent {count} packets in 3 seconds")
    except Exception as e:
        print(f"  Rapid fire failed: {e}")

    # ── Test 8: Try same but with CMD 65 rapid fire ──
    print("\n[8] Rapid fire CMD 65 — 20Hz for 3 seconds")
    print("  WATCH THE MOTORS!")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((DRONE_IP, CMD_PORT))
        s.settimeout(1)

        start = time.time()
        count = 0
        while time.time() - start < 3:
            body = make_flight_body_A(throttle=0xAA, cmd=1)
            try:
                send_lewei_persistent(s, 65, 0, body)
                count += 1
            except BrokenPipeError:
                print("  Connection broken during rapid fire")
                break
            time.sleep(0.05)

        s.settimeout(0.5)
        try:
            resp = s.recv(4096)
            print(f"  Got {len(resp)} bytes back: {resp.hex()[:80]}")
        except socket.timeout:
            pass
        s.close()
        print(f"  Sent {count} packets in 3 seconds")
    except Exception as e:
        print(f"  Rapid fire failed: {e}")

    # ── Test 9: Send raw serial bytes (no lewei framing) directly to 8060 ──
    print("\n[9] Raw bytes to TCP:8060 (bypass lewei protocol)")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((DRONE_IP, CMD_PORT))

        raw_pkts = [
            make_flight_body_A(throttle=0xFF, cmd=1),
            make_flight_body_B(throttle=0xFF, cmd=1),
            bytes([0x55, 0xAA, CENTER, CENTER, 0xFF, CENTER, 0x01, 0x00]),
        ]
        for raw in raw_pkts:
            s.sendall(raw)
            print(f"  Sent raw: {raw.hex()}")
            time.sleep(0.2)

        s.settimeout(1)
        try:
            resp = s.recv(4096)
            print(f"  Response: {resp.hex()[:80]}")
        except socket.timeout:
            print("  No response to raw bytes")
        s.close()
    except Exception as e:
        print(f"  Raw test failed: {e}")

    # Save results
    path = f"flight_test_{int(time.time())}.json"
    with open(path, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\nResults saved to {path}")

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    responded = [e for e in log if e["responded"]]
    print(f"  {len(responded)}/{len(log)} commands got responses")
    print()
    print("  Did any motors spin or twitch?")
    print("  If yes: tell me which test number!")
    print("  If no: software control is not possible with this drone.")
    print("         Best option: buy a Tello ($90) for VLA project.")
