"""
TYH TY-T6 DRONE CONTROLLER — Ultimate Protocol Finder.
Run: python drone_controller.py

Tries THREE known drone protocols simultaneously:
  A) 19-byte (0x66..0x99) — generic wifi-ufo
  B) 8-byte (0xCC..0x33) — FQ777/Cheerson (with TCP:8888 handshake)
  C) ~124-byte (0xEF header) — LSRC-S1S/reversing-wifi-uav (rolling counters)

Also:
  - Sends on ALL candidate ports (8800, 8895, 40000, 8080)
  - Listens on ALL ports for responses
  - Sniffs ALL network traffic (requires root for full sniff, works without for UDP)
  - Logs everything to JSON with full hex dumps
  - Prints live analysis

TO CAPTURE PHONE APP TRAFFIC:
  1. Connect Mac to drone WiFi
  2. Run: sudo python drone_controller.py --sniff
  3. Open TYH Fly app on phone, connect to same drone WiFi, fly around
  4. Ctrl+C to stop — analyze the JSON log
"""
import socket
import json
import struct
import sys
import time
import threading
from collections import Counter, defaultdict

DRONE_IP = "192.168.0.1"
CENTER = 0x80

# All ports to try sending on
SEND_PORTS = [8800, 8895, 40000, 8080, 7060]

# All ports to listen on
LISTEN_UDP_PORTS = [8800, 8895, 8888, 40000, 8080, 1234, 7060, 50000, 554, 6000, 9060]
LISTEN_TCP_PORTS = [7060, 8060, 8888]

# FQ777 handshake blob (from py_wifi_drone)
FQ777_HANDSHAKE = bytes([
    0x49, 0x54, 0x64, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
])


class DroneController:
    def __init__(self, drone_ip=DRONE_IP, sniff_mode=False):
        self.drone_ip = drone_ip
        self.sniff_mode = sniff_mode
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._running = False
        self._roll = CENTER
        self._pitch = CENTER
        self._throttle = CENTER
        self._yaw = CENTER
        self._cmd = 0
        self._cmd_hold_frames = 0
        self._counter1 = 0  # for protocol C
        self._counter2 = 0
        self._counter3 = 0
        self._log = []
        self._log_lock = threading.Lock()
        self._pkt_count = 0
        self._rx_count = 0
        self._response_ports = set()

    def _log_event(self, direction, proto, port, data, note=""):
        entry = {
            "time": round(time.time(), 4),
            "dir": direction,
            "proto": proto,
            "port": port,
            "data_hex": data.hex(),
            "data_len": len(data),
            "note": note,
        }
        with self._log_lock:
            self._log.append(entry)

        if direction == "RX":
            self._rx_count += 1
            ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in data[:50])
            print(f"\n  *** [{proto}:{port}] <<< {len(data):4d}b | {data[:50].hex()} | {ascii_repr} | {note}")
        elif self._pkt_count <= 5 or "probe" in note or "handshake" in note:
            print(f"  [{proto}:{port}] >>> {len(data):4d}b | {data[:30].hex()} | {note}")

    # ── Protocol A: 19-byte (0x66..0x99) ──

    def _build_A(self):
        pkt = bytearray(19)
        pkt[0] = 0x66
        pkt[1] = self._roll
        pkt[2] = self._pitch
        pkt[3] = self._throttle
        pkt[4] = self._yaw
        pkt[5] = self._cmd
        pkt[18] = 0x99
        return bytes(pkt)

    # ── Protocol B: 8-byte FQ777 (0xCC..0x33) ──

    def _build_B(self):
        pkt = bytearray(8)
        pkt[0] = 0xCC
        pkt[1] = self._roll
        pkt[2] = self._pitch
        pkt[3] = self._throttle
        pkt[4] = self._yaw
        pkt[5] = self._cmd
        pkt[6] = (pkt[1] ^ pkt[2] ^ pkt[3] ^ pkt[4] ^ pkt[5]) & 0xFF
        pkt[7] = 0x33
        return bytes(pkt)

    # ── Protocol C: ~124-byte LSRC-S1S (0xEF header, rolling counters) ──

    def _build_C(self):
        # Message header (12 bytes)
        header = bytes([0xef, 0x02, 0x7c, 0x00, 0x02, 0x02, 0x00, 0x01, 0x02, 0x00, 0x00, 0x00])

        # Counter 1 (2 bytes, little-endian)
        c1 = struct.pack('<H', self._counter1 & 0xFFFF)
        c1_suffix = bytes([0x00, 0x00, 0x14, 0x00, 0x66, 0x14])

        # Control (6 bytes)
        headless = 0x02  # headless off
        control = bytes([self._roll, self._pitch, self._throttle, self._yaw, self._cmd, headless])

        # Control suffix (10 bytes)
        ctrl_suffix = bytes(10)

        # Checksum (1 byte)
        checksum = bytes([self._roll ^ self._pitch ^ self._throttle ^ self._yaw ^ self._cmd ^ headless])

        # Checksum suffix (51 bytes)
        chk_suffix = bytearray(51)
        chk_suffix[0] = 0x99
        chk_suffix[47] = 0x32
        chk_suffix[48] = 0x4b
        chk_suffix[49] = 0x14
        chk_suffix[50] = 0x2d

        # Counter 2
        c2 = struct.pack('<H', self._counter2 & 0xFFFF)
        c2_suffix = bytes(18)

        # Counter 3
        c3 = struct.pack('<H', self._counter3 & 0xFFFF)
        c3_suffix = bytes(14)

        self._counter1 += 1
        self._counter2 += 1
        self._counter3 += 1

        return header + c1 + c1_suffix + control + ctrl_suffix + checksum + bytes(chk_suffix) + c2 + c2_suffix + c3 + c3_suffix

    def _send_udp(self, data, port, note=""):
        try:
            self.udp_sock.sendto(data, (self.drone_ip, port))
            self._pkt_count += 1
            self._log_event("TX", "UDP", port, data, note)
        except Exception:
            pass

    # ── Background threads ──

    def _cmd_loop(self):
        """Send ALL three protocols on ALL ports at ~20Hz."""
        while self._running:
            if self.sniff_mode:
                time.sleep(0.1)
                continue

            pkt_a = self._build_A()
            pkt_b = self._build_B()
            pkt_c = self._build_C()

            note = f"r=0x{self._roll:02x} p=0x{self._pitch:02x} t=0x{self._throttle:02x} y=0x{self._yaw:02x} cmd={self._cmd}"

            for port in SEND_PORTS:
                self._send_udp(pkt_a, port, f"proto-A {note}")
                self._send_udp(pkt_b, port, f"proto-B {note}")
                self._send_udp(pkt_c, port, f"proto-C {note}")

            if self._cmd in (1, 2, 4, 8):
                if self._cmd_hold_frames > 0:
                    self._cmd_hold_frames -= 1
                else:
                    self._cmd = 0
            time.sleep(0.05)

    def _init_probe_loop(self):
        """Try various init/handshake sequences."""
        if self.sniff_mode:
            return

        time.sleep(0.5)
        print("\n  [PROBE] Running init sequences...\n")

        # Video start (0xEF 0x00 0x04 0x00)
        video_init = bytes([0xef, 0x00, 0x04, 0x00])
        for port in SEND_PORTS:
            self._send_udp(video_init, port, f"probe: video-init")
            time.sleep(0.1)

        # FQ777 TCP handshake on 8888
        print("  [PROBE] Trying FQ777 TCP handshake on 8888...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((self.drone_ip, 8888))
            s.sendall(FQ777_HANDSHAKE)
            self._log_event("TX", "TCP", 8888, FQ777_HANDSHAKE, "FQ777 handshake")
            print("  [PROBE] TCP:8888 connected! Sent handshake!")
            s.settimeout(2)
            try:
                resp = s.recv(4096)
                if resp:
                    self._log_event("RX", "TCP", 8888, resp, "FQ777 handshake response!")
            except socket.timeout:
                print("  [PROBE] TCP:8888 no response to handshake")
            s.close()
        except Exception as e:
            print(f"  [PROBE] TCP:8888 failed: {e}")

        # lewei_cmd on 8060
        print("  [PROBE] Sending lewei heartbeat on TCP:8060...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((self.drone_ip, 8060))
            # lewei heartbeat command
            magic = b'lewei_cmd\x00'
            hdr_ints = struct.pack('<9I', 1, 0, 0, 0, 0, 0, 0, 0, 0)  # cmd=1=heartbeat
            lewei_pkt = magic + hdr_ints
            s.sendall(lewei_pkt)
            self._log_event("TX", "TCP", 8060, lewei_pkt, "lewei heartbeat")
            s.settimeout(2)
            try:
                resp = s.recv(4096)
                if resp:
                    self._log_event("RX", "TCP", 8060, resp, "lewei heartbeat response!")
                    print(f"  [PROBE] TCP:8060 responded! {len(resp)}b: {resp[:40].hex()}")
            except socket.timeout:
                print("  [PROBE] TCP:8060 no response to heartbeat")
            s.close()
        except Exception as e:
            print(f"  [PROBE] TCP:8060 failed: {e}")

        # lewei get_baudrate on 8060 (to see FC serial config)
        print("  [PROBE] Querying FC baud rate via lewei...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((self.drone_ip, 8060))
            magic = b'lewei_cmd\x00'
            hdr_ints = struct.pack('<9I', 35, 0, 0, 0, 0, 0, 0, 0, 0)  # cmd=35=getbaudrate
            lewei_pkt = magic + hdr_ints
            s.sendall(lewei_pkt)
            self._log_event("TX", "TCP", 8060, lewei_pkt, "lewei get_baudrate")
            s.settimeout(2)
            try:
                resp = s.recv(4096)
                if resp:
                    self._log_event("RX", "TCP", 8060, resp, "lewei baudrate response!")
                    # Parse response - skip magic(10) + header(36) = 46 bytes, then body
                    if len(resp) >= 46:
                        body = resp[46:]
                        print(f"  [PROBE] FC BAUD RATE response: {resp[:50].hex()}")
                        print(f"  [PROBE] Body: {body.hex() if body else 'empty'}")
                        # Try to parse as int
                        if len(body) >= 4:
                            baud = struct.unpack('<I', body[:4])[0]
                            print(f"  [PROBE] FC BAUD RATE = {baud}")
                    else:
                        print(f"  [PROBE] Short response: {resp.hex()}")
            except socket.timeout:
                print("  [PROBE] No baudrate response")
            s.close()
        except Exception as e:
            print(f"  [PROBE] baudrate query failed: {e}")

        # Try TCP 9060 (UART bridge)
        print("  [PROBE] Trying TCP:9060 (UART bridge)...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((self.drone_ip, 9060))
            print("  [PROBE] TCP:9060 CONNECTED! UART bridge is open!")
            # Send all protocols through it
            for name, pkt in [("A", self._build_A()), ("B", self._build_B())]:
                s.sendall(pkt)
                self._log_event("TX", "TCP", 9060, pkt, f"uart-bridge proto-{name}")
                time.sleep(0.1)
            s.settimeout(2)
            try:
                resp = s.recv(4096)
                if resp:
                    self._log_event("RX", "TCP", 9060, resp, "UART bridge response!")
            except socket.timeout:
                pass
            s.close()
        except Exception as e:
            print(f"  [PROBE] TCP:9060: {e}")

        # Full TCP port scan on likely ports
        print("\n  [PROBE] Quick TCP port scan...")
        open_ports = []
        for port in [80, 443, 554, 1234, 5000, 5555, 6000, 7060, 8060, 8080, 8800, 8888, 8895, 9060, 40000, 50000, 60000]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                s.connect((self.drone_ip, port))
                s.close()
                open_ports.append(port)
            except Exception:
                pass
        print(f"  [PROBE] Open TCP ports: {open_ports if open_ports else 'none found'}")
        print("  [PROBE] Done.\n")

    def _listen_udp_loop(self):
        """Listen on all UDP ports."""
        listeners = []
        for port in LISTEN_UDP_PORTS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                s.settimeout(0.3)
                listeners.append((s, port))
            except OSError:
                pass

        bound = [str(p) for _, p in listeners]
        print(f"  [LISTEN] UDP ports: {', '.join(bound)}")

        while self._running:
            for s, port in listeners:
                try:
                    data, addr = s.recvfrom(4096)
                    if data and addr[0] != socket.gethostbyname(socket.gethostname()):
                        self._response_ports.add(("UDP", port))
                        self._log_event("RX", "UDP", port, data, f"from {addr}")
                except socket.timeout:
                    pass
                except Exception:
                    pass

        for s, _ in listeners:
            s.close()

    def _listen_tcp_loop(self):
        """Monitor TCP ports for incoming data."""
        socks = {}
        for port in LISTEN_TCP_PORTS:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((self.drone_ip, port))
                s.settimeout(0.3)
                socks[port] = s
                print(f"  [LISTEN] TCP:{port} connected")
            except Exception:
                pass

        while self._running:
            for port, s in list(socks.items()):
                try:
                    data = s.recv(4096)
                    if data:
                        self._response_ports.add(("TCP", port))
                        self._log_event("RX", "TCP", port, data, f"tcp data ({len(data)}b)")
                except socket.timeout:
                    pass
                except Exception:
                    try:
                        s.close()
                    except Exception:
                        pass
                    del socks[port]

        for s in socks.values():
            try:
                s.close()
            except Exception:
                pass

    def _sniff_loop(self):
        """If scapy is available, sniff ALL traffic on the WiFi interface."""
        try:
            from scapy.all import sniff as scapy_sniff, IP, UDP, TCP
        except ImportError:
            print("  [SNIFF] scapy not available, skipping packet sniff")
            return

        print("  [SNIFF] Capturing ALL WiFi traffic (looking for phone app packets)...")
        print("  [SNIFF] Open TYH Fly app on phone and fly the drone!\n")

        def handle_pkt(pkt):
            if IP not in pkt:
                return
            src = pkt[IP].src
            dst = pkt[IP].dst
            # Only care about traffic to/from drone or from phone
            if self.drone_ip not in (src, dst):
                return
            # Skip our own traffic (from this Mac)
            if UDP in pkt:
                payload = bytes(pkt[UDP].payload) if pkt[UDP].payload else b""
                if payload:
                    self._log_event("SNIFF", "UDP", pkt[UDP].dport, payload,
                                    f"{src}:{pkt[UDP].sport}->{dst}:{pkt[UDP].dport}")
            elif TCP in pkt:
                payload = bytes(pkt[TCP].payload) if pkt[TCP].payload else b""
                if payload:
                    self._log_event("SNIFF", "TCP", pkt[TCP].dport, payload,
                                    f"{src}:{pkt[TCP].sport}->{dst}:{pkt[TCP].dport}")

        try:
            scapy_sniff(prn=handle_pkt, store=False, stop_filter=lambda x: not self._running)
        except PermissionError:
            print("  [SNIFF] Need root for full sniff. Run with: sudo python drone_controller.py --sniff")
        except Exception as e:
            print(f"  [SNIFF] Error: {e}")

    def _status_loop(self):
        """Status line every 5s."""
        while self._running:
            time.sleep(5)
            mode = "SNIFF" if self.sniff_mode else "CTRL"
            status = f"  [{mode}] sent={self._pkt_count} | received={self._rx_count}"
            if self._response_ports:
                status += f" | RESPONDING: {self._response_ports}"
            with self._log_lock:
                rx_entries = [e for e in self._log if e["dir"] in ("RX", "SNIFF")]
            if rx_entries:
                last = rx_entries[-1]
                status += f" | last_rx: [{last['proto']}:{last['port']}] {last['data_hex'][:30]}..."
            print(status)

    # ── Connect ──

    def connect(self):
        mode_str = "SNIFF MODE (capturing phone app traffic)" if self.sniff_mode else "CONTROL MODE (sending all protocols)"
        print("=" * 70)
        print(f"  TYH TY-T6 — {mode_str}")
        print("=" * 70)
        print()
        print(f"  Drone IP: {self.drone_ip}")
        print(f"  Sending protocols: A(19b) + B(8b) + C(124b) on ports {SEND_PORTS}")
        print(f"  Listening UDP: {LISTEN_UDP_PORTS}")
        print(f"  Listening TCP: {LISTEN_TCP_PORTS}")
        print()

        self._running = True

        threads = [
            ("CMD-all-protos", self._cmd_loop),
            ("Init-probes", self._init_probe_loop),
            ("UDP-listen", self._listen_udp_loop),
            ("TCP-listen", self._listen_tcp_loop),
            ("Sniffer", self._sniff_loop),
            ("Status", self._status_loop),
        ]
        for name, target in threads:
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()

        print(f"  Started {len(threads)} threads.\n")

    def disconnect(self):
        self._running = False
        time.sleep(0.3)
        try:
            self.udp_sock.close()
        except Exception:
            pass
        self._save_log()
        self._print_analysis()

    def _save_log(self):
        path = f"drone_log_{int(time.time())}.json"
        with self._log_lock:
            with open(path, "w") as f:
                json.dump(self._log, f, indent=2)
            print(f"\nSaved {len(self._log)} log entries to {path}")

    def _print_analysis(self):
        print("\n" + "=" * 70)
        print("  SESSION ANALYSIS")
        print("=" * 70)

        with self._log_lock:
            entries = list(self._log)

        tx = [e for e in entries if e["dir"] == "TX"]
        rx = [e for e in entries if e["dir"] == "RX"]
        sniffed = [e for e in entries if e["dir"] == "SNIFF"]

        print(f"\n  Packets sent:    {len(tx)}")
        print(f"  Packets received: {len(rx)}")
        print(f"  Packets sniffed:  {len(sniffed)}")

        if self._response_ports:
            print(f"  Ports that responded: {self._response_ports}")

        if rx:
            print("\n  --- RECEIVED DATA (responses to our probes) ---")
            for e in rx[:30]:
                ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in bytes.fromhex(e["data_hex"][:80]))
                print(f"  [{e['proto']}:{e['port']}] {e['data_hex'][:80]} | {ascii_repr} | {e['note']}")

        if sniffed:
            print(f"\n  --- SNIFFED TRAFFIC ({len(sniffed)} packets) ---")
            # Group by flow
            flows = defaultdict(list)
            for e in sniffed:
                flows[e["note"]].append(e)

            for flow, pkts in sorted(flows.items(), key=lambda x: -len(x[1])):
                sizes = Counter(e["data_len"] for e in pkts)
                size_str = ", ".join(f"{sz}b x{c}" for sz, c in sizes.most_common(5))
                print(f"\n  {flow}: {len(pkts)} packets | sizes: {size_str}")
                # Show first few unique payloads
                seen = []
                for p in pkts:
                    if p["data_hex"] not in seen:
                        seen.append(p["data_hex"])
                    if len(seen) >= 5:
                        break
                for h in seen[:3]:
                    raw = bytes.fromhex(h[:100])
                    ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in raw)
                    print(f"    {h[:100]}")
                    print(f"    {ascii_repr}")

                # Byte analysis if packets are small enough and we have enough samples
                if len(pkts) >= 5 and pkts[0]["data_len"] <= 200:
                    pkt_size = pkts[0]["data_len"]
                    if all(p["data_len"] == pkt_size for p in pkts[:50]):
                        samples = [bytes.fromhex(p["data_hex"]) for p in pkts[:100]]
                        print(f"\n    BYTE ANALYSIS ({pkt_size} bytes, {len(samples)} samples):")
                        for pos in range(min(pkt_size, 50)):
                            values = set(s[pos] for s in samples if pos < len(s))
                            if len(values) == 1:
                                print(f"      [{pos:3d}] FIXED  0x{list(values)[0]:02x}")
                            elif len(values) <= 5:
                                vals_str = " ".join(f"0x{v:02x}" for v in sorted(values))
                                print(f"      [{pos:3d}] VARIES {vals_str}")
                            else:
                                all_vals = [s[pos] for s in samples if pos < len(s)]
                                print(f"      [{pos:3d}] VARIES range 0x{min(all_vals):02x}-0x{max(all_vals):02x} ({len(values)} unique) <-- LIKELY CONTROL DATA")

        print("\n" + "=" * 70)

    # ── Flight commands ──

    def takeoff(self):
        self._cmd = 1
        self._cmd_hold_frames = 20
        print(">>> TAKEOFF")

    def land(self):
        self._cmd = 2
        self._cmd_hold_frames = 20
        print(">>> LAND")

    def stop(self):
        self._cmd = 4
        self._cmd_hold_frames = 20
        print(">>> EMERGENCY STOP")

    def calibrate_gyro(self):
        self._cmd = 8
        self._cmd_hold_frames = 20
        print(">>> GYRO CALIBRATE")

    def set_controls(self, roll=None, pitch=None, throttle=None, yaw=None):
        if roll is not None:
            self._roll = max(0, min(255, roll))
        if pitch is not None:
            self._pitch = max(0, min(255, pitch))
        if throttle is not None:
            self._throttle = max(0, min(255, throttle))
        if yaw is not None:
            self._yaw = max(0, min(255, yaw))

    def get_state(self):
        return {
            "roll": f"0x{self._roll:02x}",
            "pitch": f"0x{self._pitch:02x}",
            "throttle": f"0x{self._throttle:02x}",
            "yaw": f"0x{self._yaw:02x}",
            "command": self._cmd,
            "packets_sent": self._pkt_count,
            "packets_received": self._rx_count,
            "responding_ports": list(self._response_ports) if self._response_ports else "none",
        }


if __name__ == "__main__":
    sniff = "--sniff" in sys.argv
    drone = DroneController(sniff_mode=sniff)
    drone.connect()

    try:
        if sniff:
            print("SNIFF MODE: Watching for phone app traffic.")
            print("Open TYH Fly on phone, connect to drone WiFi, fly around.")
            print("Press Ctrl+C when done to see analysis.\n")
            while True:
                time.sleep(1)
        else:
            print("Flight:   t=takeoff  l=land  s=stop  g=gyro cal")
            print("Throttle: u=up  d=down")
            print("Move:     w=forward  a=left  ss=back  dd=right")
            print("Yaw:      j=left  k=right")
            print("Other:    c=center  p=state  x=save  q=quit\n")

            while True:
                try:
                    cmd = input("> ").strip().lower()
                except EOFError:
                    break
                if cmd == "t":
                    drone.takeoff()
                elif cmd == "l":
                    drone.land()
                elif cmd == "s":
                    drone.stop()
                elif cmd == "g":
                    drone.calibrate_gyro()
                elif cmd == "u":
                    t = min(255, drone._throttle + 20)
                    drone.set_controls(throttle=t)
                    print(f"Throttle: 0x{t:02x} ({t})")
                elif cmd == "d":
                    t = max(0, drone._throttle - 20)
                    drone.set_controls(throttle=t)
                    print(f"Throttle: 0x{t:02x} ({t})")
                elif cmd == "w":
                    drone.set_controls(pitch=0xAA)
                    print("Pitch forward")
                elif cmd == "a":
                    drone.set_controls(roll=0x55)
                    print("Roll left")
                elif cmd == "ss":
                    drone.set_controls(pitch=0x55)
                    print("Pitch back")
                elif cmd == "dd":
                    drone.set_controls(roll=0xAA)
                    print("Roll right")
                elif cmd == "j":
                    drone.set_controls(yaw=0x55)
                    print("Yaw left")
                elif cmd == "k":
                    drone.set_controls(yaw=0xAA)
                    print("Yaw right")
                elif cmd == "c":
                    drone.set_controls(roll=CENTER, pitch=CENTER, yaw=CENTER)
                    print("Centered")
                elif cmd == "p":
                    print(json.dumps(drone.get_state(), indent=2))
                elif cmd == "x":
                    drone._save_log()
                elif cmd == "q":
                    drone.land()
                    time.sleep(1)
                    break
                else:
                    print("t/l/s/g/u/d/w/a/ss/dd/j/k/c/p/x/q")
    except KeyboardInterrupt:
        pass
    finally:
        drone.disconnect()
