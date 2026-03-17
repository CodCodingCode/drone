"""
Live object detection on TYH T-6 drone camera feed using RF-DETR Nano.

The drone streams MJPEG frames via pylwdrone. Each frame is decoded with
OpenCV, then RF-DETR Nano runs COCO 80-class detection, displayed in a
real-time OpenCV window.

Usage:
  python detect_live.py                    # run with defaults
  python detect_live.py --threshold 0.3    # lower confidence threshold
  python detect_live.py --skip 2           # detect every 2nd frame

Prerequisites:
  pip install rfdetr opencv-python
  # Cache model weights on normal WiFi first:
  python -c "from rfdetr import RFDETRNano; RFDETRNano()"
"""

import argparse
import signal
import threading
import time
from collections import deque
from queue import Empty, Full, Queue

import cv2
import numpy as np
import pylwdrone
import supervision as sv
from rfdetr import RFDETRNano

COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)


def drone_feed_thread(frame_queue: Queue, stop: threading.Event):
    """Read MJPEG frames from drone, decode to BGR, put into queue."""
    try:
        drone = pylwdrone.LWDrone()
        print("Connected to drone camera.")
        frame_count = 0
        for frame in drone.start_video_stream():
            if stop.is_set():
                break
            data = frame.frame_bytes
            # Decode JPEG to BGR numpy array
            img = cv2.imdecode(
                np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if img is None:
                continue
            frame_count += 1
            if frame_count == 1:
                print(f"First frame decoded: {img.shape[1]}x{img.shape[0]}")
            # Drop old frames to keep latency low
            try:
                frame_queue.put_nowait(img)
            except Full:
                try:
                    frame_queue.get_nowait()
                except Empty:
                    pass
                try:
                    frame_queue.put_nowait(img)
                except Full:
                    pass
    except Exception as e:
        if not stop.is_set():
            print(f"Drone feed error: {e}")
    finally:
        stop.set()


def main():
    parser = argparse.ArgumentParser(description="Drone live detection with RF-DETR Nano")
    parser.add_argument("--threshold", type=float, default=0.5, help="Detection confidence threshold")
    parser.add_argument("--skip", type=int, default=0, help="Run detection every N frames (0=every frame)")
    args = parser.parse_args()

    # Load model
    print("Loading RF-DETR Nano model...")
    model = RFDETRNano()
    print("Model loaded.")

    # Annotators
    box_annotator = sv.BoxAnnotator()
    label_annotator = sv.LabelAnnotator()

    # Frame queue and threads
    frame_queue: Queue = Queue(maxsize=2)
    stop = threading.Event()

    def on_sigint(sig, frame):
        print("\nCaught Ctrl+C...")
        stop.set()

    signal.signal(signal.SIGINT, on_sigint)

    feeder = threading.Thread(target=drone_feed_thread, args=(frame_queue, stop), daemon=True)
    feeder.start()

    print("Waiting for first frame from drone...")

    fps_times = deque(maxlen=30)
    frame_idx = 0
    last_detections = None
    last_labels = None

    try:
        while not stop.is_set():
            try:
                frame = frame_queue.get(timeout=0.5)
            except Empty:
                continue

            now = time.time()
            fps_times.append(now)
            frame_idx += 1

            if frame_idx == 1:
                print("Starting detection...")

            # Run detection (or reuse previous)
            skip = args.skip
            if skip <= 0 or frame_idx % (skip + 1) == 1 or last_detections is None:
                detections = model.predict(frame, threshold=args.threshold)
                labels = []
                for cls_id, conf in zip(detections.class_id, detections.confidence):
                    name = COCO_CLASSES[cls_id] if cls_id < len(COCO_CLASSES) else f"class_{cls_id}"
                    labels.append(f"{name} {conf:.2f}")
                last_detections = detections
                last_labels = labels
            else:
                detections = last_detections
                labels = last_labels

            # Annotate
            annotated = box_annotator.annotate(scene=frame.copy(), detections=detections)
            annotated = label_annotator.annotate(
                scene=annotated, detections=detections, labels=labels
            )

            # FPS overlay
            if len(fps_times) > 1:
                fps = (len(fps_times) - 1) / (fps_times[-1] - fps_times[0])
            else:
                fps = 0.0
            cv2.putText(
                annotated, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2,
            )
            cv2.putText(
                annotated, f"Objects: {len(detections)}", (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2,
            )

            cv2.imshow("Drone Detection - RF-DETR Nano", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        print("\nShutting down...")
        stop.set()
        cv2.destroyAllWindows()
        feeder.join(timeout=2)
        print("Done.")


if __name__ == "__main__":
    main()
