"""
core/verifier.py
----------------
AI Verification Engine — Phase 3 (YOLOv8 Logo / Watermark Detection).

Loads a YOLOv8 model and runs inference on flagged frames to determine
whether a sports logo or watermark is present, providing an additional
layer of ownership confirmation beyond pHash similarity alone.
"""

from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Ultralytics import is deferred so the rest of the system works even
# if YOLOv8 is not yet installed.
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError as e:
    print(f"DEBUG: YOLOv8 Import Failed: {e}")
    YOLO_AVAILABLE = False
except Exception as e:
    print(f"DEBUG: YOLOv8 Unexpected Error: {e}")
    YOLO_AVAILABLE = False


# ─── Constants ────────────────────────────────────────────────────────────────

# Default model — yolov8n (nano) is fast and suitable for CI / demo use.
DEFAULT_MODEL: str = "yolov8n.pt"

# COCO classes that commonly appear in sports broadcast footage.
# In a production system, replace with a custom-trained logo detector.
SPORTS_RELEVANT_CLASSES: set[str] = {
    "sports ball", "person", "tv", "laptop", "cell phone",
    "remote", "chair", "cup",          # broadcast studio props
}

# Confidence threshold for treating a detection as valid.
CONFIDENCE_THRESHOLD: float = 0.45


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """YOLO inference result for a single frame."""
    timestamp: float
    logo_detected: bool = False
    confidence: float = 0.0
    detected_classes: list[str] = field(default_factory=list)
    annotated_frame: Optional[np.ndarray] = None  # Frame with drawn boxes


# ─── YOLO Engine ──────────────────────────────────────────────────────────────

class LogoVerifier:
    """
    Wraps a YOLOv8 model to detect logos / watermarks in video frames.

    Usage
    -----
    verifier = LogoVerifier()
    result = verifier.verify_frame(timestamp=4.0, frame_bgr=frame)
    if result.logo_detected:
        print(f"Logo found at {result.timestamp}s — confidence {result.confidence:.2%}")
    """

    def __init__(self, model_path: str = DEFAULT_MODEL) -> None:
        if not YOLO_AVAILABLE:
            raise ImportError(
                "The 'ultralytics' package is not installed. "
                "Run: pip install ultralytics"
            )
        self.model = YOLO(model_path)
        self.model_path = model_path

    def verify_frame(
        self,
        timestamp: float,
        frame_bgr: np.ndarray,
        conf_threshold: float = CONFIDENCE_THRESHOLD,
        draw_boxes: bool = True,
    ) -> DetectionResult:
        """
        Run YOLOv8 inference on a single video frame.

        The method checks detected object class names against a set of
        sports-relevant COCO classes. A custom-trained logo detection
        model would replace this heuristic in production.

        Parameters
        ----------
        timestamp      : Seconds into the video (for reporting).
        frame_bgr      : OpenCV BGR frame.
        conf_threshold : Minimum confidence for a valid detection.
        draw_boxes     : If True, annotate the frame with bounding boxes.

        Returns
        -------
        DetectionResult with logo_detected flag and metadata.
        """
        result = DetectionResult(timestamp=timestamp)

        # Run inference
        predictions = self.model(frame_bgr, conf=conf_threshold, verbose=False)

        detected: list[str] = []
        best_conf: float = 0.0
        annotated = frame_bgr.copy()

        for pred in predictions:
            boxes = pred.boxes
            if boxes is None:
                continue

            for box in boxes:
                cls_id = int(box.cls[0])
                cls_name = self.model.names[cls_id]
                conf = float(box.conf[0])

                detected.append(cls_name)
                if conf > best_conf:
                    best_conf = conf

                # Draw bounding box if requested
                if draw_boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    colour = (0, 255, 80) if cls_name in SPORTS_RELEVANT_CLASSES else (60, 60, 255)
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), colour, 2)
                    label = f"{cls_name} {conf:.0%}"
                    cv2.putText(
                        annotated, label,
                        (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, colour, 2,
                    )

        result.detected_classes = detected
        result.confidence = best_conf
        result.annotated_frame = annotated

        # Logo detected if any sports-relevant class is found
        result.logo_detected = bool(
            set(detected) & SPORTS_RELEVANT_CLASSES
        )

        return result

    def verify_frames(
        self,
        frames: list[tuple[float, np.ndarray]],
        conf_threshold: float = CONFIDENCE_THRESHOLD,
    ) -> list[DetectionResult]:
        """Batch verify a list of (timestamp, frame_bgr) tuples."""
        return [
            self.verify_frame(ts, frame, conf_threshold)
            for ts, frame in frames
        ]
