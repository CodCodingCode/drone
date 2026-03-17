"""
UART Sniffer — capture and decode the FC serial protocol.

Run: python uart_sniff.py /dev/tty.usbserial-XXXX

Connect your USB-to-serial adapter's RX pin to the FC's RX line
(the wire going FROM camera TO flight controller) and GND to GND.

This will show you exactly what bytes the RC controller generates
(relayed through the camera module) so we can replay them.
"""
import serial
import sys
import time
import json
from collections import Counter, defaultdict

BAUD = 115200  # confirmed from lewei get_baudrate


def find_packets(data, min_len=4, max_len=64):
    """Try to find repeating packet boundaries in raw serial data."""
    # Look for common header bytes
    headers = [0x55, 0xAA, 0x66, 0xCC, 0xFF, 0xEF, 0x5A, 0xA5]
    results = {}

    for h in headers:
        positions = [i for i, b in enumerate(data) if b == h]
        if len(positions) < 3:
            continue

        # Check distances between header bytes — consistent distance = packet length
        dists = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
        dist_counts = Counter(dists)
        most_common_dist, count = dist_counts.most_common(1)[0]

        if count >= 3 and min_len <= most_common_dist <= max_len:
            results[h] = {
                "header": f"0x{h:02x}",
                "packet_len": most_common_dist,
                "occurrences": count,
                "confidence": count / len(dists),
            }

    return results


def analyze_packets(packets):
    """Byte-by-byte analysis of captured packets."""
    if not packets:
        return

    pkt_len = len(packets[0])
    print(f"\n  BYTE ANALYSIS ({pkt_len} bytes/packet, {len(packets)} packets):")
    print(f"  {'Pos':>4s} | {'Hex':>5s} | {'Range':>11s} | {'Unique':>6s} | Role")
    print(f"  {'-'*4}-+-{'-'*5}-+-{'-'*11}-+-{'-'*6}-+-{'-'*20}")

    for pos in range(pkt_len):
        values = [p[pos] for p in packets if pos < len(p)]
        unique = len(set(values))
        vmin, vmax = min(values), max(values)

        if unique == 1:
            role = f"FIXED = 0x{values[0]:02x}"
            if pos == 0:
                role += " (header)"
            elif pos == pkt_len - 1:
                role += " (footer)"
        elif unique <= 3:
            vals = sorted(set(values))
            role = f"FLAG: {', '.join(f'0x{v:02x}' for v in vals)}"
        elif vmax - vmin > 50:
            role = "*** STICK/CONTROL ***"
        elif vmax - vmin > 10:
            role = "varies (trim/config?)"
        else:
            role = "varies slightly"

        print(f"  [{pos:3d}] | 0x{values[0]:02x}  | 0x{vmin:02x} - 0x{vmax:02x} | {unique:5d}  | {role}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python uart_sniff.py <serial-port>")
        print()
        print("Find your port:")
        print("  ls /dev/tty.usb*")
        print("  ls /dev/cu.usb*")
        print()

        # Try to list available ports
        import glob
        ports = glob.glob("/dev/tty.usb*") + glob.glob("/dev/cu.usb*")
        if ports:
            print(f"Found ports: {ports}")
        else:
            print("No USB serial ports found. Plug in your USB-to-UART adapter.")
        sys.exit(1)

    port = sys.argv[1]
    print("=" * 70)
    print(f"  UART SNIFFER — {port} @ {BAUD} baud")
    print("=" * 70)
    print()
    print("  Listening for FC serial data...")
    print("  Move the RC controller sticks to see commands change.")
    print("  Press Ctrl+C to stop and analyze.\n")

    ser = serial.Serial(port, BAUD, timeout=0.1)
    raw_data = bytearray()
    packets_log = []
    start_time = time.time()
    last_print = 0
    byte_count = 0

    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                raw_data.extend(chunk)
                byte_count += len(chunk)
                now = time.time()

                # Print hex dump every 0.5s
                if now - last_print > 0.5:
                    elapsed = now - start_time
                    rate = byte_count / elapsed if elapsed > 0 else 0
                    # Show last 64 bytes
                    tail = raw_data[-64:]
                    hex_str = " ".join(f"{b:02x}" for b in tail)
                    print(f"  [{elapsed:6.1f}s] {byte_count:6d}B ({rate:.0f} B/s) | ...{hex_str}")
                    last_print = now

    except KeyboardInterrupt:
        pass
    finally:
        ser.close()

    elapsed = time.time() - start_time
    print(f"\n\nCaptured {len(raw_data)} bytes in {elapsed:.1f}s")

    if len(raw_data) < 10:
        print("Not enough data captured. Check wiring:")
        print("  - RX on adapter → wire going from camera to FC")
        print("  - GND on adapter → drone GND")
        print("  - Drone powered on")
        print("  - RC controller on and paired")
        sys.exit(1)

    # Save raw data
    raw_path = f"uart_raw_{int(time.time())}.bin"
    with open(raw_path, "wb") as f:
        f.write(raw_data)
    print(f"Raw data saved to {raw_path}")

    # Analyze
    print("\n" + "=" * 70)
    print("  PROTOCOL ANALYSIS")
    print("=" * 70)

    # Byte frequency
    freq = Counter(raw_data)
    print(f"\n  Most common bytes:")
    for byte, count in freq.most_common(10):
        pct = count / len(raw_data) * 100
        print(f"    0x{byte:02x} ({byte:3d}): {count:6d} ({pct:.1f}%)")

    # Find packet structure
    print(f"\n  Looking for packet boundaries...")
    found = find_packets(raw_data)
    if found:
        for h, info in sorted(found.items(), key=lambda x: -x[1]["occurrences"]):
            print(f"    Header 0x{h:02x}: packet_len={info['packet_len']}, found {info['occurrences']}x (confidence: {info['confidence']:.0%})")

        # Extract packets using best header
        best = max(found.items(), key=lambda x: x[1]["occurrences"])
        header_byte = best[0]
        pkt_len = best[1]["packet_len"]
        print(f"\n  Extracting packets: header=0x{header_byte:02x}, len={pkt_len}")

        packets = []
        i = 0
        while i < len(raw_data) - pkt_len:
            if raw_data[i] == header_byte:
                pkt = bytes(raw_data[i:i+pkt_len])
                packets.append(pkt)
                i += pkt_len
            else:
                i += 1

        print(f"  Extracted {len(packets)} packets")

        if packets:
            # Show first 5
            print(f"\n  First 5 packets:")
            for p in packets[:5]:
                print(f"    {p.hex()}")

            # Byte analysis
            analyze_packets(packets)

            # Save as JSON
            pkt_log = [{"hex": p.hex(), "bytes": list(p)} for p in packets]
            json_path = f"uart_packets_{int(time.time())}.json"
            with open(json_path, "w") as f:
                json.dump({
                    "header": f"0x{header_byte:02x}",
                    "packet_length": pkt_len,
                    "baud": BAUD,
                    "total_packets": len(packets),
                    "packets": pkt_log,
                }, f, indent=2)
            print(f"\n  Packets saved to {json_path}")
    else:
        print("  No clear packet structure found.")
        print("  The data might be encrypted, or the wiring might be wrong.")
        print(f"\n  First 200 bytes: {raw_data[:200].hex()}")

    print("\nDone!")
