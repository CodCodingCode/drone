#!/bin/bash
# Capture TYH Fly app traffic from iPhone via USB.
#
# Steps:
#   1. Connect iPhone to Mac via USB cable
#   2. Run: bash capture_phone.sh
#   3. Open TYH Fly app, connect to drone WiFi on phone, fly around
#   4. Ctrl+C to stop
#   5. Then run: python intake.py phone_capture.pcapng
#
# This uses Apple's Remote Virtual Interface (rvictl) to capture
# all iPhone network traffic through the USB connection.

set -e

echo "=== iPhone Traffic Capture for Drone Reverse Engineering ==="
echo ""

# Get iPhone UDID
echo "[1] Finding connected iPhone..."
UDID=$(system_profiler SPUSBDataType 2>/dev/null | grep -A2 "iPhone" | grep "Serial Number" | awk '{print $NF}')

if [ -z "$UDID" ]; then
    # Try xcrun
    UDID=$(xcrun xctrace list devices 2>/dev/null | grep "iPhone" | grep -oE '[A-F0-9-]{20,}' | head -1)
fi

if [ -z "$UDID" ]; then
    echo "ERROR: No iPhone found via USB!"
    echo ""
    echo "Make sure:"
    echo "  1. iPhone is connected via USB cable"
    echo "  2. You've trusted this Mac on the iPhone"
    echo "  3. Try: xcrun xctrace list devices"
    echo ""
    echo "Or manually: rvictl -s <UDID> && sudo tcpdump -i rvi0 -w phone_capture.pcapng"
    exit 1
fi

echo "Found iPhone: $UDID"

# Create remote virtual interface
echo ""
echo "[2] Creating virtual interface (rvi0)..."
rvictl -s "$UDID"

# Verify interface exists
if ! ifconfig rvi0 > /dev/null 2>&1; then
    echo "ERROR: rvi0 interface not created. Try: sudo rvictl -s $UDID"
    exit 1
fi

echo "rvi0 interface created!"

# Capture
OUTFILE="phone_capture_$(date +%s).pcapng"
echo ""
echo "[3] Starting capture on rvi0 -> $OUTFILE"
echo ""
echo "================================================"
echo "  NOW: Open TYH Fly app on iPhone"
echo "  Connect to drone WiFi on the phone"
echo "  Fly the drone around for 30+ seconds"
echo "  Press Ctrl+C when done"
echo "================================================"
echo ""

sudo tcpdump -i rvi0 -w "$OUTFILE" -v 'host 192.168.0.1'

# Cleanup
echo ""
echo "[4] Cleaning up..."
rvictl -x "$UDID"

echo ""
echo "Capture saved to: $OUTFILE"
echo "Analyze with: python intake.py $OUTFILE"
