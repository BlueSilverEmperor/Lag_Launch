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

MATCH_THRESHOLD: int = 8          # D_H < threshold → frame is a match
SPEED_FACTORS: list = [0.9, 1.0, 1.1]  # ±10% speed variation trials
TEMPORAL_WINDOW: int = 3          # Consecutive frames needed for strong match
OVERLAY_THRESHOLD_BOOST: int = 3  # Extra tolerance for frames with overlays


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


# ─── Advanced Scan with Speed-Invariance & Temporal Check ─────────────────────

def scan_suspect_video_advanced(
    suspect_hashes: dict[str, str],
    suspect_video_name: str,
    hash_db: dict,
    threshold: int = MATCH_THRESHOLD,
    speed_invariant: bool = True,
    temporal_check: bool = True,
    overlay_tolerance: bool = True,
) -> SimilarityReport:
    """
    Enhanced scan with:
    - Speed-invariant matching (±10% playback speed compensation)
    - Temporal window validation (requires N consecutive frames to match)
    - Overlay-tolerant threshold (slightly relaxed for frames with meme text/logo)
    """
    report = SimilarityReport(
        suspect_video=suspect_video_name,
        total_frames_checked=len(suspect_hashes),
    )

    # Sort timestamps so temporal window check works correctly
    sorted_items = sorted(suspect_hashes.items(), key=lambda x: float(x[0]))

    # Build a multi-speed version of the hash_db keys for speed-invariant lookup
    # We pre-index the DB frames by clip for fast adjacent timestamp lookup
    clip_ts_index: dict[str, list[tuple[float, str]]] = {}
    for clip_name, frame_hashes in hash_db.items():
        clip_ts_index[clip_name] = sorted(
            [(float(ts), h) for ts, h in frame_hashes.items()],
            key=lambda x: x[0]
        )

    raw_results: list[FrameMatchResult] = []

    for ts_str, s_hash in sorted_items:
        suspect_ts = float(ts_str)

        # Try multiple effective thresholds: normal + overlay-boosted
        thresholds_to_try = [threshold]
        if overlay_tolerance:
            thresholds_to_try.append(threshold + OVERLAY_THRESHOLD_BOOST)

        best_result = FrameMatchResult(
            suspect_timestamp=suspect_ts,
            suspect_hash=s_hash,
        )

        for clip_name, ts_list in clip_ts_index.items():
            if not ts_list:
                continue

            for ref_ts, ref_hash in ts_list:
                try:
                    dist = hamming_distance(s_hash, ref_hash)
                except Exception:
                    continue

                if dist < best_result.best_distance:
                    best_result.best_distance = dist
                    best_result.matched_clip = clip_name
                    best_result.matched_timestamp = ref_ts

        # Apply speed-invariant search: also look up DB frames at ±10% timestamp
        if speed_invariant and best_result.matched_clip:
            clip_name = best_result.matched_clip
            ts_list = clip_ts_index.get(clip_name, [])
            for factor in [f for f in SPEED_FACTORS if f != 1.0]:
                adjusted_ts = suspect_ts * factor
                # Find nearest DB frame to the speed-adjusted timestamp
                nearest = min(
                    ts_list,
                    key=lambda x: abs(x[0] - adjusted_ts),
                    default=None
                )
                if nearest:
                    try:
                        dist = hamming_distance(s_hash, nearest[1])
                        if dist < best_result.best_distance:
                            best_result.best_distance = dist
                            best_result.matched_timestamp = nearest[0]
                    except Exception:
                        pass

        # Determine match using the effective threshold
        eff_threshold = threshold + OVERLAY_THRESHOLD_BOOST if overlay_tolerance else threshold
        if best_result.best_distance < eff_threshold:
            best_result.is_match = True

        raw_results.append(best_result)

    # Temporal window validation: require at least 2-of-3 consecutive frames to match
    if temporal_check and len(raw_results) >= TEMPORAL_WINDOW:
        validated: list[FrameMatchResult] = []
        n = len(raw_results)
        for i, fr in enumerate(raw_results):
            if fr.is_match:
                # Look at neighboring frames
                window = raw_results[max(0, i-1):min(n, i+2)]
                neighbour_matches = sum(1 for w in window if w.best_distance < threshold + OVERLAY_THRESHOLD_BOOST + 4)
                # Require at least 1 other frame nearby to be a near-match
                if neighbour_matches >= 2:
                    validated.append(fr)
                else:
                    # Isolated single-frame match — downgrade to unmatched (noise filter)
                    fr.is_match = False
                    validated.append(fr)
            else:
                validated.append(fr)
        raw_results = validated

    report.frame_results = raw_results
    report.matched_frames = sum(1 for fr in raw_results if fr.is_match)
    return report
