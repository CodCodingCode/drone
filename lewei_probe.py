"""
Probe ALL lewei command types on TCP:8060 to find flight control.

The camera module responded to lewei heartbeat and baudrate queries.
Maybe flight control is a lewei command we haven't tried yet.
This script tries every command ID (0-255) and logs which ones respond.

Run: python lewei_probe.py
"""
import socket
import struct
import time
import json

DRONE_IP = "192.168.0.1"
CMD_PORT = 8060

MAGIC = b'lewei_cmd\x00'

# Known command IDs from pylwdrone
KNOWN = {
    1: "heartbeat", 2: "startstream", 3: "stopstream", 4: "settime",
    5: "gettime", 6: "getrecplan", 8: "getreclist", 9: "startreplay",
    16: "stopreplay", 17: "setrecplan", 18: "getfile", 19: "takepic",
    20: "delfile", 21: "reformatsd", 22: "setwifiname", 23: "setwifipass",
    24: "setwifichan", 25: "restartwifi", 32: "setwifidefs",
    33: "getcamflip", 34: "setcamflip", 35: "getbaudrate", 36: "setbaudrate",
    37: "getconfig", 38: "setconfig", 39: "getpiclist", 40: "get1080p",
    42: "getresolution", 43: "setresolution", 48: "getrectime", 49: "setrectime",
}


def send_lewei_cmd(cmd_id, arg1=0, body=b"", timeout=2):
    """Send a lewei command and return the response."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((DRONE_IP, CMD_PORT))

        # Build header: magic(10) + 9 x uint32(36) = 46 bytes
        hdr = struct.pack('<9I', cmd_id, arg1, 0, len(body), 0, 0, 0, 0, 0)
        packet = MAGIC + hdr + body
        s.sendall(packet)

        # Read response
        try:
            resp = s.recv(4096)
            s.close()
            return resp
        except socket.timeout:
            s.close()
            return None
    except Exception as e:
        return None


def parse_response(resp):
    """Parse lewei response header."""
    if not resp or len(resp) < 46:
        return None
    if resp[:10] != MAGIC:
        return {"raw": resp.hex(), "note": "non-lewei response"}
    ints = struct.unpack('<9I', resp[10:46])
    body = resp[46:]
    return {
        "cmd": ints[0],
        "arg1": ints[1],
        "arg2": ints[2],
        "body_size": ints[3],
        "int4": ints[4],
        "int5": ints[5],
        "int6": ints[6],
        "int7": ints[7],
        "int8": ints[8],
        "body_hex": body.hex() if body else "",
        "body_ascii": body.decode("ascii", errors="replace") if body else "",
        "raw_hex": resp.hex(),
    }


if __name__ == "__main__":
    print("=" * 70)
    print("  LEWEI COMMAND PROBE — Finding flight control commands")
    print("  Testing all command IDs (0-255) on TCP:8060")
    print("=" * 70)

    results = []

    # First, get config (has lots of info)
    print("\n[1] Getting drone config...")
    resp = send_lewei_cmd(37)  # getconfig
    if resp:
        parsed = parse_response(resp)
        if parsed:
            print(f"  Config response: {len(resp)} bytes")
            print(f"  Args: cmd={parsed.get('cmd')} arg1={parsed.get('arg1')}")
            if parsed.get("body_hex"):
                print(f"  Body ({len(parsed['body_hex'])//2} bytes): {parsed['body_hex'][:200]}")
                print(f"  ASCII: {parsed.get('body_ascii', '')[:200]}")
            results.append({"cmd_id": 37, "name": "getconfig", "response": parsed})

    # Get heartbeat
    print("\n[2] Heartbeat...")
    resp = send_lewei_cmd(1)
    if resp:
        parsed = parse_response(resp)
        if parsed:
            print(f"  Heartbeat: arg1=0x{parsed.get('arg1', 0):08x}")
            print(f"  Body: {parsed.get('body_hex', '')[:100]}")
            results.append({"cmd_id": 1, "name": "heartbeat", "response": parsed})

    # Get baud rate
    print("\n[3] FC Baud rate...")
    resp = send_lewei_cmd(35)
    if resp:
        parsed = parse_response(resp)
        if parsed:
            baud = parsed.get("arg1", 0)
            print(f"  FC baud rate: {baud}")
            results.append({"cmd_id": 35, "name": "getbaudrate", "response": parsed})

    # Now scan ALL command IDs
    print("\n[4] Scanning all command IDs (0-255)...")
    print("  (looking for unknown commands that might be flight control)\n")

    for cmd_id in range(256):
        name = KNOWN.get(cmd_id, f"unknown-{cmd_id}")
        resp = send_lewei_cmd(cmd_id)

        if resp:
            parsed = parse_response(resp)
            marker = "  *** " if cmd_id not in KNOWN else "  "
            resp_cmd = parsed.get("cmd", "?") if parsed else "?"
            resp_arg = parsed.get("arg1", "?") if parsed else "?"
            body = parsed.get("body_hex", "")[:60] if parsed else ""
            print(f"{marker}CMD {cmd_id:3d} ({name:20s}) -> RESPONDED! cmd={resp_cmd} arg1={resp_arg} body={body}")
            results.append({"cmd_id": cmd_id, "name": name, "response": parsed})
        else:
            if cmd_id % 50 == 0:
                print(f"  CMD {cmd_id:3d}... (no response)")

        time.sleep(0.1)  # don't overwhelm the drone

    # Summary
    print("\n" + "=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    print(f"\n  {len(results)} commands got responses:\n")
    for r in results:
        known = "KNOWN" if r["cmd_id"] in KNOWN else "UNKNOWN"
        name = r["name"]
        resp = r.get("response", {})
        print(f"  CMD {r['cmd_id']:3d} [{known:7s}] {name:20s} | arg1={resp.get('arg1', '?')} body_len={len(resp.get('body_hex', ''))//2}")

    # Save full results
    path = f"lewei_probe_{int(time.time())}.json"
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Full results saved to {path}")

    # Try sending raw bytes through potential UART passthrough commands
    print("\n\n[5] Trying to send flight data through lewei commands...")

    # Try various arg values and body data that might activate flight control
    flight_tests = [
        # Maybe there's a "send to UART" command
        (100, 0, b"\x66\x80\x80\x80\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x99", "uart passthrough cmd=100"),
        (101, 0, b"\x66\x80\x80\x80\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x99", "uart passthrough cmd=101"),
        (200, 0, b"\x66\x80\x80\x80\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x99", "uart passthrough cmd=200"),
        # Maybe command 36 (setbaudrate) with special args does something
        (36, 115200, b"", "setbaudrate 115200"),
        # Try with control data as body
        (1, 0, b"\x66\x80\x80\xff\x80\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x99", "heartbeat with flight body"),
    ]

    for cmd_id, arg1, body, desc in flight_tests:
        print(f"  Trying: {desc} (cmd={cmd_id}, arg1={arg1}, body={len(body)}b)...")
        resp = send_lewei_cmd(cmd_id, arg1=arg1, body=body)
        if resp:
            parsed = parse_response(resp)
            print(f"    -> RESPONDED: {parsed.get('raw_hex', '')[:80] if parsed else resp.hex()[:80]}")
        else:
            print(f"    -> no response")
        time.sleep(0.2)

    print("\nDone! Check the JSON log for full details.")
