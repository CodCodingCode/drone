"""
TYH T-6 Camera Connection using pylwdrone.
The TYH T-6 uses a Lewei (LW) camera module — same as many com.lwcx drones.

Usage:
  python camera_connect.py              # test connection + take photo
  python camera_connect.py --stream     # stream live video to ffplay
  python camera_connect.py --save       # save 5 seconds of video to file
"""
import pylwdrone
import sys
import time
import argparse


def test_connection():
    """Test basic connection to the drone camera."""
    print("Connecting to drone camera...")
    drone = pylwdrone.LWDrone()

    print("Connected! Testing commands...\n")

    # Take a picture
    print("[1] Taking a picture...")
    try:
        pic = drone.take_picture()
        with open("drone_photo.jpg", "wb") as f:
            f.write(pic.data)
        print(f"    Saved drone_photo.jpg ({pic.size} bytes, path={pic.path})")
    except Exception as e:
        print(f"    Photo failed: {e}")

    print("\nDone! Camera connection works.")
    return drone


def stream_video():
    """Stream live video — pipe to ffplay for display."""
    print("Connecting to drone camera...")
    drone = pylwdrone.LWDrone()

    print("Streaming video to stdout. Usage:")
    print("  python camera_connect.py --stream | ffplay -i -")
    print("  (or pipe to ffmpeg to save)\n")

    for frame in drone.start_video_stream():
        sys.stdout.buffer.write(frame.frame_bytes)
        sys.stdout.buffer.flush()


def save_video(duration=5):
    """Save raw H.264 video to file."""
    print(f"Connecting to drone camera...")
    drone = pylwdrone.LWDrone()

    filename = f"drone_video_{int(time.time())}.h264"
    print(f"Recording {duration}s of video to {filename}...")

    total_bytes = 0
    frame_count = 0
    start = time.time()

    with open(filename, "wb") as f:
        for frame in drone.start_video_stream():
            f.write(frame.frame_bytes)
            total_bytes += len(frame.frame_bytes)
            frame_count += 1

            if frame_count % 30 == 0:
                elapsed = time.time() - start
                print(f"  {frame_count} frames, {total_bytes / 1024:.1f} KB, {elapsed:.1f}s")

            if time.time() - start >= duration:
                break

    elapsed = time.time() - start
    print(f"\nSaved {filename}")
    print(f"  {frame_count} frames, {total_bytes / 1024:.1f} KB in {elapsed:.1f}s")
    print(f"  Play with: ffplay {filename}")


def capture_frames_for_vla(duration=10):
    """
    Capture individual frames as JPEGs for VLA training.
    Saves frames to drone_frames/ directory.
    """
    import os
    os.makedirs("drone_frames", exist_ok=True)

    print(f"Connecting to drone camera...")
    drone = pylwdrone.LWDrone()

    print(f"Capturing frames for {duration}s to drone_frames/...")

    frame_count = 0
    start = time.time()

    for frame in drone.start_video_stream():
        # Save each frame
        path = f"drone_frames/frame_{frame_count:06d}.bin"
        with open(path, "wb") as f:
            f.write(frame.frame_bytes)
        frame_count += 1

        if frame_count % 30 == 0:
            elapsed = time.time() - start
            print(f"  {frame_count} frames captured ({elapsed:.1f}s)")

        if time.time() - start >= duration:
            break

    print(f"\nCaptured {frame_count} frames to drone_frames/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TYH T-6 Camera")
    parser.add_argument("--stream", action="store_true", help="Stream video to stdout")
    parser.add_argument("--save", action="store_true", help="Save video to file")
    parser.add_argument("--frames", action="store_true", help="Capture frames for VLA training")
    parser.add_argument("--duration", type=int, default=5, help="Recording duration in seconds")
    args = parser.parse_args()

    if args.stream:
        stream_video()
    elif args.save:
        save_video(args.duration)
    elif args.frames:
        capture_frames_for_vla(args.duration)
    else:
        test_connection()
