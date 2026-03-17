"""
Drone PCAP analyzer — reverse-engineer the command protocol.
Run: python intake.py <pcapfile>
If no file given, defaults to the saved wireshark capture.

Captures from the phone app (TYH Fly) while flying will reveal
the real command format, ports, and packet structure.
"""
import json
import sys
from collections import Counter, defaultdict
from scapy.all import rdpcap, UDP, TCP, IP


def analyze(pcap_path):
    packets = rdpcap(pcap_path)
    print(f"Loaded {len(packets)} packets from {pcap_path}\n")

    udp_packets = []
    tcp_packets = []

    for pkt in packets:
        if IP not in pkt:
            continue
        entry = {
            "src_ip": pkt[IP].src,
            "dst_ip": pkt[IP].dst,
            "time": float(pkt.time),
        }
        if UDP in pkt:
            payload = bytes(pkt[UDP].payload) if pkt[UDP].payload else b""
            entry.update({
                "proto": "UDP",
                "src_port": pkt[UDP].sport,
                "dst_port": pkt[UDP].dport,
                "payload_len": len(payload),
                "payload_hex": payload.hex(),
                "payload_raw": payload,
            })
            udp_packets.append(entry)
        elif TCP in pkt:
            payload = bytes(pkt[TCP].payload) if pkt[TCP].payload else b""
            entry.update({
                "proto": "TCP",
                "src_port": pkt[TCP].sport,
                "dst_port": pkt[TCP].dport,
                "payload_len": len(payload),
                "payload_hex": payload.hex(),
                "payload_raw": payload,
            })
            tcp_packets.append(entry)

    # ── Summary by flow (ip:port -> ip:port) ──
    print("=" * 70)
    print("FLOW SUMMARY")
    print("=" * 70)
    flows = defaultdict(lambda: {"count": 0, "sizes": [], "proto": ""})
    for pkt in udp_packets + tcp_packets:
        key = f"{pkt['src_ip']}:{pkt['src_port']} -> {pkt['dst_ip']}:{pkt['dst_port']}"
        flows[key]["count"] += 1
        flows[key]["sizes"].append(pkt["payload_len"])
        flows[key]["proto"] = pkt["proto"]

    for flow, info in sorted(flows.items(), key=lambda x: -x[1]["count"]):
        sizes = info["sizes"]
        non_zero = [s for s in sizes if s > 0]
        size_counts = Counter(non_zero).most_common(5)
        size_str = ", ".join(f"{sz}b x{c}" for sz, c in size_counts) if size_counts else "no payload"
        print(f"  [{info['proto']}] {flow}")
        print(f"         {info['count']} pkts | sizes: {size_str}")
        print()

    # ── Command pattern analysis ──
    # Group packets with payload by (proto, dst_port, length) to find repeating command structures
    print("=" * 70)
    print("COMMAND PATTERNS (grouped by proto + dst_port + packet length)")
    print("=" * 70)
    groups = defaultdict(list)
    for pkt in udp_packets + tcp_packets:
        if pkt["payload_len"] == 0:
            continue
        key = (pkt["proto"], pkt["dst_port"], pkt["payload_len"])
        groups[key].append(pkt)

    for (proto, port, size), pkts in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"\n  [{proto}] port {port}, {size} bytes — {len(pkts)} packets")

        # Show first few unique payloads
        seen = []
        for p in pkts:
            h = p["payload_hex"]
            if h not in seen:
                seen.append(h)
            if len(seen) >= 8:
                break

        if len(seen) == 1:
            print(f"    ALL IDENTICAL: {seen[0]}")
        else:
            print(f"    {len(seen)} unique payloads (of {len(pkts)} total):")
            for h in seen:
                raw = bytes.fromhex(h)
                ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
                print(f"      HEX: {h}")
                print(f"      ASC: {ascii_repr}")

        # Byte-position analysis: find which bytes change vs stay constant
        if len(pkts) >= 3 and size <= 64:
            print(f"\n    BYTE ANALYSIS (which bytes change across {min(len(pkts), 200)} samples):")
            samples = [bytes.fromhex(p["payload_hex"]) for p in pkts[:200]]
            for pos in range(size):
                values = set(s[pos] for s in samples)
                if len(values) == 1:
                    label = "FIXED"
                    detail = f"0x{samples[0][pos]:02x}"
                elif len(values) <= 5:
                    label = "VARIES"
                    detail = ", ".join(f"0x{v:02x}" for v in sorted(values))
                else:
                    vals = [s[pos] for s in samples]
                    label = "VARIES"
                    detail = f"range 0x{min(vals):02x}-0x{max(vals):02x} ({len(values)} unique)"
                marker = " <-- CONTROL?" if label == "VARIES" and 3 < len(values) else ""
                print(f"      byte[{pos:2d}]: {label:7s} {detail}{marker}")

    # ── Timing analysis for command rate ──
    print("\n" + "=" * 70)
    print("TIMING (command send rate)")
    print("=" * 70)
    for (proto, port, size), pkts in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(pkts) < 10:
            continue
        times = [p["time"] for p in pkts]
        deltas = [times[i+1] - times[i] for i in range(len(times)-1)]
        avg_delta = sum(deltas) / len(deltas) if deltas else 0
        hz = 1.0 / avg_delta if avg_delta > 0 else 0
        print(f"  [{proto}] port {port}, {size}b: ~{hz:.1f} Hz (avg {avg_delta*1000:.1f}ms between packets)")

    # ── Export to JSON (without raw bytes) ──
    export = []
    for pkt in udp_packets + tcp_packets:
        e = {k: v for k, v in pkt.items() if k != "payload_raw"}
        export.append(e)

    out_path = pcap_path.rsplit(".", 1)[0] + "_analysis.json"
    with open(out_path, "w") as f:
        json.dump(export, f, indent=2)
    print(f"\nFull packet data exported to {out_path}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/Users/owner/saved wireshark info.pcapng"
    analyze(path)
