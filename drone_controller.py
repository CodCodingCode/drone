"""
Step 2: Python drone controller for TYH T-6.
Based on common WiFi drone protocol (0x66...0x99 packets).

NOTE: Run capture_drone.py first to confirm the exact IP, port, and packet
structure for YOUR drone. Then adjust the constants below if needed.
"""
import socket
import time
import threading


# -- Adjust these after running capture_drone.py --
DRONE_IP = "192.168.0.1"
CMD_PORT = 8800          # command port (common: 8800 or 40000)
VIDEO_PORT = 1234        # video stream port
VIDEO_START_CMD = bytes([0xef, 0x00, 0x04, 0x00])

# Control centers
CENTER = 128
THROTTLE_OFF = 0


class DroneController:
    def __init__(self, drone_ip=DRONE_IP, cmd_port=CMD_PORT):
        self.drone_ip = drone_ip
        self.cmd_port = cmd_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._running = False
        self._roll = CENTER
        self._pitch = CENTER
        self._throttle = THROTTLE_OFF
        self._yaw = CENTER
        self._cmd = 0  # 0=idle, 1=takeoff, 2=stop, 3=land, 4=gyro_cal
        self._headless = 0
        self._send_thread = None

    def _build_packet(self):
        """Build a 20-byte command packet (0x66 header, 0x99 terminator)."""
        pkt = bytearray(20)
        pkt[0] = 0x66           # header
        pkt[1] = 0x80           # reserved
        pkt[2] = self._roll
        pkt[3] = self._pitch
        pkt[4] = self._throttle
        pkt[5] = self._yaw
        pkt[6] = self._cmd
        pkt[7] = self._headless
        # bytes 8-17 reserved/zero
        pkt[18] = pkt[2] ^ pkt[3] ^ pkt[4] ^ pkt[5] ^ pkt[6] ^ pkt[7]  # checksum
        pkt[19] = 0x99          # terminator
        return bytes(pkt)

    def _send_loop(self):
        """Send commands at ~50Hz (every 20ms) to keep the drone alive."""
        while self._running:
            pkt = self._build_packet()
            self.sock.sendto(pkt, (self.drone_ip, self.cmd_port))
            # Reset one-shot commands after sending
            if self._cmd in (1, 2, 3, 4):
                self._cmd = 0
            time.sleep(0.02)

    def connect(self):
        """Start sending commands to the drone."""
        self._running = True
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()
        print(f"Connected: sending commands to {self.drone_ip}:{self.cmd_port}")

    def disconnect(self):
        self._running = False
        if self._send_thread:
            self._send_thread.join(timeout=1)
        self.sock.close()
        print("Disconnected.")

    def start_video(self):
        """Tell the drone to start streaming video."""
        self.sock.sendto(VIDEO_START_CMD, (self.drone_ip, self.cmd_port))
        print(f"Video start command sent. Listen on UDP port {VIDEO_PORT} for H.264 stream.")

    # -- Flight commands --
    def takeoff(self):
        self._cmd = 1
        print("TAKEOFF")

    def land(self):
        self._cmd = 3
        print("LAND")

    def stop(self):
        self._cmd = 2
        print("EMERGENCY STOP")

    def calibrate_gyro(self):
        self._cmd = 4
        print("GYRO CALIBRATE")

    def set_controls(self, roll=CENTER, pitch=CENTER, throttle=THROTTLE_OFF, yaw=CENTER):
        """Set stick positions. All values 0-255, 128=center."""
        self._roll = max(0, min(255, roll))
        self._pitch = max(0, min(255, pitch))
        self._throttle = max(0, min(255, throttle))
        self._yaw = max(0, min(255, yaw))

    # -- Convenience methods for logging/VLA training --
    def get_state(self):
        """Return current control state as a dict (for logging training data)."""
        return {
            "timestamp": time.time(),
            "roll": self._roll,
            "pitch": self._pitch,
            "throttle": self._throttle,
            "yaw": self._yaw,
            "command": self._cmd,
        }


# -- Quick test --
if __name__ == "__main__":
    drone = DroneController()
    drone.connect()

    try:
        print("\nCommands: t=takeoff, l=land, s=stop, g=gyro cal, v=video, q=quit")
        print("Use WASD for roll/pitch, UP/DOWN arrows for throttle (in a real UI)\n")

        while True:
            cmd = input("> ").strip().lower()
            if cmd == "t":
                drone.takeoff()
            elif cmd == "l":
                drone.land()
            elif cmd == "s":
                drone.stop()
            elif cmd == "g":
                drone.calibrate_gyro()
            elif cmd == "v":
                drone.start_video()
            elif cmd == "q":
                drone.land()
                time.sleep(1)
                break
            else:
                print("Unknown command")
    finally:
        drone.disconnect()
