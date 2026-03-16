import socket
import time

drone_ip = "192.168.0.1"
control_port = 8800

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_command(roll=0x80, pitch=0x80, throttle=0x80, yaw=0x80):
    # Build packet - exact structure varies, use Wireshark to verify
    packet = bytearray(19)
    packet[0] = 0x66
    packet[1] = roll
    packet[2] = pitch  
    packet[3] = throttle
    packet[4] = yaw
    packet[18] = 0x99  # end byte
    sock.sendto(bytes(packet), (drone_ip, control_port))

# Takeoff
send_command(throttle=0xAA)
time.sleep(3)
# Hover
send_command()