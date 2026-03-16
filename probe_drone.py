"""
Probe the drone directly from the Mac.
Tries common IPs and ports used by cheap WiFi drones.
Run while connected to the drone's WiFi.
"""
import socket
import time

# Common drone IPs
IPS = ["192.168.0.1", "192.168.1.1", "172.16.10.1", "10.0.0.1"]

# Common drone command ports
PORTS = [8800, 8080, 40000, 7060, 8888, 50000, 8895, 6000]

# Common init/probe packets
PROBES = [
    bytes([0x66, 0x80, 0x80, 0x80, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00,
           0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0x99]),  # 20-byte idle cmd
    bytes([0xef, 0x00, 0x04, 0x00]),  # video start
    bytes([0x63, 0x63, 0x01, 0x00, 0x00, 0x00, 0x00]),  # heartbeat
    b"command",  # Tello-style text command
    bytes([0xff, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]),  # generic probe
]


def probe(ip, port, data, timeout=1.0):
    """Send a UDP probe and listen for a response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(data, (ip, port))
        resp, addr = sock.recvfrom(4096)
        return resp, addr
    except socket.timeout:
        return None, None
    except Exception as e:
        return None, None
    finally:
        sock.close()


def try_tcp(ip, port, timeout=1.0):
    """Try a TCP connection to see if anything is listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        sock.close()
        return True
    except:
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Drone Probe - Finding your drone on the network")
    print("=" * 60)

    # First, find the gateway IP (likely the drone)
    print("\n[1] Checking gateway/router IP...")
    import subprocess
    try:
        result = subprocess.run(["route", "get", "default"], capture_output=True, text=True)
        for line in result.stdout.split("\n"):
            if "gateway" in line:
                gw = line.split(":")[-1].strip()
                if gw and gw not in IPS:
                    IPS.insert(0, gw)
                print(f"    Gateway: {gw}")
    except:
        pass

    # TCP port scan on likely IPs
    print("\n[2] TCP port scan on candidate IPs...")
    TCP_PORTS = [80, 443, 7060, 8080, 8800, 8888, 9090, 554, 1234, 40000]
    for ip in IPS:
        for port in TCP_PORTS:
            if try_tcp(ip, port, timeout=0.5):
                print(f"    OPEN: {ip}:{port} (TCP)")

    # UDP probes
    print("\n[3] Sending UDP probes...")
    for ip in IPS:
        for port in PORTS:
            for i, data in enumerate(PROBES):
                resp, addr = probe(ip, port, data, timeout=0.5)
                if resp:
                    print(f"    RESPONSE from {addr} on port {port}!")
                    print(f"    Probe #{i}: {data.hex()}")
                    print(f"    Response: {resp.hex()}")
                    print(f"    Response (ascii): {resp}")
                    print()

    print("\n[4] Listening for any incoming UDP for 5 seconds...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    local_port = sock.getsockname()[1]
    sock.settimeout(1.0)
    print(f"    Listening on port {local_port}")

    # Also try binding to common video ports
    listeners = []
    for vport in [1234, 8800, 8080, 7060]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("0.0.0.0", vport))
            s.settimeout(1.0)
            listeners.append((s, vport))
            print(f"    Listening on port {vport}")
        except:
            pass

    end = time.time() + 5
    while time.time() < end:
        for s, p in listeners + [(sock, local_port)]:
            try:
                data, addr = s.recvfrom(4096)
                print(f"    RECEIVED on port {p} from {addr}: {data[:50].hex()}...")
            except socket.timeout:
                pass

    for s, _ in listeners:
        s.close()
    sock.close()

    print("\nDone. If nothing was found, the drone may use TCP or a non-standard protocol.")
    print("Try: 1) Make sure drone is ON  2) Make sure Mac is on drone WiFi  3) Open TYH Fly app on phone")
