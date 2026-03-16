import json
from scapy.all import rdpcap, UDP, IP

packets = rdpcap("/Users/owner/saved wireshark info.pcapng")

results = []
for pkt in packets:
    if UDP in pkt:
        payload = bytes(pkt[UDP].payload) if pkt[UDP].payload else b""
        results.append({
            "src_ip": pkt[IP].src if IP in pkt else None,
            "dst_ip": pkt[IP].dst if IP in pkt else None,
            "src_port": pkt[UDP].sport,
            "dst_port": pkt[UDP].dport,
            "payload_len": len(payload),
            "payload_hex": payload.hex(),
            "payload_ascii": payload.decode("ascii", errors="replace"),
        })

with open("drone_packets.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"Wrote {len(results)} UDP packets to drone_packets.json")
