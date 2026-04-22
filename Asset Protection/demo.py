"""
demo.py — Test Video Generator
==============================

Generates synthetic test videos entirely in memory using OpenCV.
Useful for testing the DAP GUI without needing real video files.

Usage
-----
  python demo.py
"""

from __future__ import annotations

from pathlib import Path
import cv2
import numpy as np

# ─── Paths ────────────────────────────────────────────────────────────────────
DEMO_DIR    = Path("demo_clips")
SUSPECT_DIR = Path("demo_suspect")
OFFICIAL    = DEMO_DIR    / "official_v1.mp4"
PIRATED     = SUSPECT_DIR / "pirated_v1.mp4"

# ─── Video parameters ─────────────────────────────────────────────────────────
FPS      = 25
DURATION = 12          # seconds
W, H     = 640, 360


# ─── Synthetic video generators ───────────────────────────────────────────────

def _make_official_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FPS,
        (W, H),
    )

    colours = [
        (30, 80, 200), (200, 60, 30), (30, 180, 80),
        (180, 40, 180), (200, 160, 20), (20, 160, 200),
    ]

    for frame_idx in range(FPS * DURATION):
        t = frame_idx / FPS
        seg = int(t // 2) % len(colours)
        b, g, r = colours[seg]

        frame = np.zeros((H, W, 3), dtype=np.uint8)
        for y in range(H):
            alpha = y / H
            frame[y] = [
                int(b * (1 - alpha) + 10 * alpha),
                int(g * (1 - alpha) + 10 * alpha),
                int(r * (1 - alpha) + 10 * alpha),
            ]

        cv2.putText(frame, "SPORTS.TV", (20, 40),
                    cv2.FONT_HERSHEY_DUPLEX, 1.2, (255, 255, 255), 2)
        cv2.putText(frame, f"OFFICIAL | t={t:.1f}s", (20, H - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 220, 220), 1)

        cx = int((frame_idx / (FPS * DURATION)) * (W - 60)) + 30
        cy = H // 2
        cv2.circle(frame, (cx, cy), 18, (255, 255, 255), -1)

        writer.write(frame)
    writer.release()


def _make_pirated_video(official_path: Path, pirated_path: Path, noise_level: int = 6) -> None:
    pirated_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(official_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    writer = cv2.VideoWriter(
        str(pirated_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (w, h),
    )

    rng = np.random.default_rng(42)
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        noise = rng.integers(-noise_level, noise_level + 1, frame.shape, dtype=np.int16)
        pirated_frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        cv2.putText(pirated_frame, "PIRATED COPY", (W // 2 - 120, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        writer.write(pirated_frame)

    cap.release()
    writer.release()


if __name__ == "__main__":
    print(f"Generating official test clip ({DURATION}s): {OFFICIAL}")
    _make_official_video(OFFICIAL)
    print(f"Generating pirated test clip with noise: {PIRATED}")
    _make_pirated_video(OFFICIAL, PIRATED, noise_level=5)
    print("Done! You can use these files to test the DAP Web GUI.")
