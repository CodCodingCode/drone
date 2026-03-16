"""
Step 1: Capture & decode drone packets.
Connect your Mac to the drone's WiFi, then run this while using the TYH Fly app
(on an emulator or phone on the same network).

This sniffs UDP traffic and decodes command packets in real time.
"""
from scapy.all import sniff, UDP, IP
import struct
import time


DRONE_IP = "192.168.0.1"  # typical for these drones, adjust if needed


def decode_command(payload):
    """Decode a typical WiFi drone command packet."""
    data = bytes(payload)
    hex_str = data.hex()

    # Look for packets starting with 0x66 and ending with 0x99
    if len(data) >= 8 and data[0] == 0x66 and data[-1] == 0x99:
        info = {"raw_hex": hex_str, "length": len(data)}

        if len(data) >= 7:
            info["roll"] = data[2]      # 0-255, 128=center
            info["pitch"] = data[3]     # 0-255, 128=center
            info["throttle"] = data[4]  # 0-255, 0=none
            info["yaw"] = data[5]       # 0-255, 128=center

        if len(data) >= 8:
            cmd_byte = data[6]
            cmd_names = {0: "idle", 1: "takeoff", 2: "stop", 3: "land", 4: "gyro_cal"}
            info["command"] = cmd_names.get(cmd_byte, f"unknown(0x{cmd_byte:02x})")

        return info

    return {"raw_hex": hex_str, "length": len(data)}


def packet_callback(pkt):
    if UDP in pkt:
        src = pkt[IP].src if IP in pkt else "?"
        dst = pkt[IP].dst if IP in pkt else "?"
        sport = pkt[UDP].sport
        dport = pkt[UDP].dport
        payload = bytes(pkt[UDP].payload)

        if len(payload) == 0:
            return

        timestamp = time.strftime("%H:%M:%S")
        decoded = decode_command(payload)

        print(f"[{timestamp}] {src}:{sport} -> {dst}:{dport} | len={len(payload)} | {decoded}")


if __name__ == "__main__":
    print("=" * 70)
    print("Drone Packet Sniffer")
    print("=" * 70)
    print(f"Listening for UDP traffic...")
    print("Connect to drone WiFi, then open TYH Fly app.")
    print("Press Ctrl+C to stop.\n")

    # Sniff all UDP - we'll figure out the exact ports from the output
    sniff(filter="udp", prn=packet_callback, store=0)
