"""
core/hasher.py
--------------
Keyframe Extraction & Perceptual Hash (pHash) Engine.

Extracts frames from a video at a fixed interval and generates a
perceptual hash for each frame using the dHash / pHash algorithm.
"""

import cv2
import imagehash
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Generator


# ─── Constants ────────────────────────────────────────────────────────────────

FRAME_INTERVAL_SEC: float = 2.0   # Extract one frame every N seconds
HASH_SIZE: int = 16                # pHash bit size (16×16 = 256-bit hash)


# ─── Public API ───────────────────────────────────────────────────────────────

def extract_frames(
    video_path: str | Path,
    interval_sec: float = FRAME_INTERVAL_SEC
) -> Generator[tuple[float, np.ndarray], None, None]:
    """
    Yield (timestamp_sec, frame_bgr) tuples from a video file.

    Parameters
    ----------
    video_path   : Path to the video file.
    interval_sec : How many seconds to skip between extracted frames.

    Yields
    ------
    (timestamp_sec, frame) where frame is a BGR numpy array.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        # Fallback for some windows drivers / protocols
        if isinstance(video_path, str) and video_path.startswith("http"):
            cap = cv2.VideoCapture(str(video_path), cv2.CAP_FFMPEG)
            
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video source: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    frame_step = max(1, int(fps * interval_sec))
    frame_idx = 0

    while True:
        if total_frames > 0 and frame_idx >= total_frames:
            break

        # Attempt precise seek
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        
        # If seek fails or frame is empty, try to read next frame
        if not ret or frame is None:
            # Maybe we reached the end or the file is truncated
            break

        timestamp = frame_idx / fps
        yield timestamp, frame

        frame_idx += frame_step
        
        # Safety check for stuck loops
        if frame_idx < 0: break 

    cap.release()


def preprocess_frame_for_hash(frame_bgr: np.ndarray) -> np.ndarray:
    """
    Normalise a frame before hashing to make pHash robust against:
    - Letterboxing / pillarboxing (black bars on any side)
    - Slight crops and zoom-ins / zoom-outs
    - Aspect-ratio padding

    Strategy
    --------
    1. Detect and strip black borders.
    2. Return the content-only region.
    If the crop would remove > 40% of pixels (i.e. the original was valid)
    we bail out and return the original to avoid over-cropping.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    DARK = 20  # pixel values below this are considered “black”

    non_black_rows = np.any(gray > DARK, axis=1)
    non_black_cols = np.any(gray > DARK, axis=0)

    if not non_black_rows.any() or not non_black_cols.any():
        return frame_bgr  # Entirely black frame — return as-is

    r0, r1 = int(np.argmax(non_black_rows)), int(len(non_black_rows) - 1 - np.argmax(non_black_rows[::-1]))
    c0, c1 = int(np.argmax(non_black_cols)), int(len(non_black_cols) - 1 - np.argmax(non_black_cols[::-1]))

    h, w = frame_bgr.shape[:2]
    crop_h = r1 - r0 + 1
    crop_w = c1 - c0 + 1

    # Only apply crop if content fills at least 50% of original frame
    if crop_h > h * 0.50 and crop_w > w * 0.50:
        return frame_bgr[r0:r0 + crop_h, c0:c0 + crop_w]

    return frame_bgr


def frame_to_pil(frame_bgr: np.ndarray) -> Image.Image:
    """Convert a BGR OpenCV frame to an RGB PIL Image."""
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def generate_phash(frame_bgr: np.ndarray, hash_size: int = HASH_SIZE) -> imagehash.ImageHash:
    """
    Generate a perceptual hash (pHash) for a single video frame.

    The frame is preprocessed to strip black bars (letterboxing / pillarboxing)
    before hashing, making the fingerprint resistant to crop, zoom, and
    aspect-ratio changes.
    """
    frame_clean = preprocess_frame_for_hash(frame_bgr)
    pil_img = frame_to_pil(frame_clean)
    return imagehash.phash(pil_img, hash_size=hash_size)


def hash_video(
    video_path: str | Path,
    interval_sec: float = FRAME_INTERVAL_SEC
) -> dict[str, str]:
    """
    Hash all keyframes in a video.

    Returns
    -------
    A dict mapping "timestamp_sec" (as a string key) → hex hash string.
    e.g. {"0.0": "f8c4a3b2...", "2.0": "f8c4a312...", ...}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[str, str] = {}
    
    # We use a ThreadPoolExecutor to parallelize the hashing process.
    # While Python has the GIL, many underlying OpenCV and NumPy operations 
    # (used by imagehash/pHash) release it, allowing for true concurrency.
    with ThreadPoolExecutor() as executor:
        future_to_ts = {}
        for timestamp, frame in extract_frames(video_path, interval_sec):
            ts_key = f"{timestamp:.2f}"
            future = executor.submit(generate_phash, frame)
            future_to_ts[future] = ts_key
            
        for future in as_completed(future_to_ts):
            ts_key = future_to_ts[future]
            try:
                h = future.result()
                results[ts_key] = str(h)
            except Exception as exc:
                print(f"Error computing pHash for {ts_key}: {exc}")

    return results


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """
    Compute the Hamming Distance between two hex hash strings.

    The Hamming Distance is the number of bit positions at which the
    two hashes differ — it is the core metric for pHash similarity:

        D_H ≈ 0          → Direct copy
        0 < D_H < 8      → Modified version (re-encoded / resized)
        D_H >= 8         → Likely different content

    Parameters
    ----------
    hash_a, hash_b : Hex strings returned by imagehash.

    Returns
    -------
    Integer Hamming distance (lower = more similar).
    """
    ih_a = imagehash.hex_to_hash(hash_a)
    ih_b = imagehash.hex_to_hash(hash_b)
    return ih_a - ih_b  # imagehash overloads __sub__ as Hamming distance
