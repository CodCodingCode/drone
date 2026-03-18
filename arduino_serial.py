import serial
ser = serial.Serial('/dev/cu.usbmodem11301', 115200, timeout=1)
while True:
    line = ser.readline().decode().strip()
    if line:
        print(line)