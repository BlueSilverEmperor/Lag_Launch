"""
core/detector.py
----------------
Similarity Detection Engine (Phase 2).

Compares suspect video frames against the stored hash database and
returns per-frame match results, including the best-match clip,
timestamp, Hamming distance, and a match/no-match flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .hasher import hamming_distance


# ─── Constants ────────────────────────────────────────────────────────────────

MATCH_THRESHOLD: int = 8   # D_H < threshold → frame is a match


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class FrameMatchResult:
    """Result of comparing one suspect frame against the entire hash DB."""
    suspect_timestamp: float      # Seconds into the suspect video
    suspect_hash: str             # Hex pHash of the suspect frame

    is_match: bool = False        # True if D_H < threshold
    best_distance: int = 999      # Lowest Hamming distance found
    matched_clip: Optional[str] = None          # Source clip name
    matched_timestamp: Optional[float] = None   # Matching timestamp in source


@dataclass
class SimilarityReport:
    """Aggregated report for an entire suspect video scan."""
    suspect_video: str
    total_frames_checked: int = 0
    matched_frames: int = 0
    frame_results: list[FrameMatchResult] = field(default_factory=list)

    @property
    def similarity_percentage(self) -> float:
        """Percentage of suspect frames that matched at least one source frame."""
        if self.total_frames_checked == 0:
            return 0.0
        return round((self.matched_frames / self.total_frames_checked) * 100, 2)

    @property
    def verdict(self) -> str:
        pct = self.similarity_percentage
        if pct >= 80:
            return "HIGH SIMILARITY — Likely Unauthorized Copy"
        elif pct >= 40:
            return "MODERATE SIMILARITY — Possible Modified Copy"
        elif pct >= 10:
            return "LOW SIMILARITY — Minor Overlap Detected"
        else:
            return "NO SIGNIFICANT MATCH — Content Appears Original"


# ─── Public API ───────────────────────────────────────────────────────────────

def load_hash_db(db_path: str | Path) -> dict:
    """Load the hash database from a JSON file."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {}
    with open(db_path, "r") as f:
        return json.load(f)


def compare_frame(
    suspect_timestamp: float,
    suspect_hash: str,
    hash_db: dict,
    threshold: int = MATCH_THRESHOLD
) -> FrameMatchResult:
    """
    Compare a single suspect frame hash against the entire hash database.

    Iterates over every stored clip and every stored timestamp, computes
    the Hamming Distance (D_H), and keeps the best (lowest) match.

    Parameters
    ----------
    suspect_timestamp : Timestamp (seconds) of the frame in the suspect video.
    suspect_hash      : Hex pHash string of the suspect frame.
    hash_db           : {clip_name: {timestamp_str: hash_hex}} dict.
    threshold         : D_H must be below this to count as a match.

    Returns
    -------
    FrameMatchResult populated with match details.
    """
    result = FrameMatchResult(
        suspect_timestamp=suspect_timestamp,
        suspect_hash=suspect_hash,
    )

    for clip_name, frame_hashes in hash_db.items():
        for ts_str, ref_hash in frame_hashes.items():
            try:
                dist = hamming_distance(suspect_hash, ref_hash)
            except Exception:
                continue

            if dist < result.best_distance:
                result.best_distance = dist
                result.matched_clip = clip_name
                result.matched_timestamp = float(ts_str)

    if result.best_distance < threshold:
        result.is_match = True

    return result


def scan_suspect_video(
    suspect_hashes: dict[str, str],
    suspect_video_name: str,
    hash_db: dict,
    threshold: int = MATCH_THRESHOLD,
) -> SimilarityReport:
    """
    Scan all keyframe hashes from a suspect video against the hash database.

    Parameters
    ----------
    suspect_hashes     : {timestamp_str: hash_hex} from the suspect video.
    suspect_video_name : Human-readable name / path of the suspect video.
    hash_db            : The persistent hash database dict.
    threshold          : Hamming distance threshold for a positive match.

    Returns
    -------
    A fully-populated SimilarityReport.
    """
    report = SimilarityReport(
        suspect_video=suspect_video_name,
        total_frames_checked=len(suspect_hashes),
    )

    for ts_str, s_hash in suspect_hashes.items():
        frame_result = compare_frame(
            suspect_timestamp=float(ts_str),
            suspect_hash=s_hash,
            hash_db=hash_db,
            threshold=threshold,
        )
        report.frame_results.append(frame_result)
        if frame_result.is_match:
            report.matched_frames += 1

    return report
