"""
core/detector.py
----------------
Phase 2: Semantic Similarity Engine via Qdrant & CLIP Embeddings.

Compares suspect video frame embeddings against the Qdrant vector database,
implementing expanded playback speed invariance (0.75x, 0.9x, 1.1x, 1.25x, 1.5x)
and timeline verification.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from .qdrant_store import QdrantStore

# ─── Constants ────────────────────────────────────────────────────────────────

# Cosine similarity threshold (1.0 = exact match).
# CLIP embeddings usually hover around 0.3 for unrelated, >0.85 for same content.
MATCH_THRESHOLD_COSINE: float = 0.85 

# Extended playback variance to catch extreme speedup/slowdown piracy
SPEED_FACTORS: list[float] = [0.75, 0.9, 1.0, 1.1, 1.25, 1.5]

TEMPORAL_WINDOW: int = 3          # Consecutive frames needed for strong match
OVERLAY_THRESHOLD_TOLERANCE: float = 0.05  # Deduct from threshold if overlays are expected


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class FrameMatchResult:
    """Result of comparing one suspect frame against the entire vector DB."""
    suspect_timestamp: float      
    suspect_embedding: Optional[np.ndarray] = field(default=None, repr=False)

    is_match: bool = False        
    best_similarity: float = 0.0  # Cosine similarity (higher is better)
    matched_clip: Optional[str] = None          
    matched_timestamp: Optional[float] = None   


@dataclass
class SimilarityReport:
    """Aggregated report for an entire suspect video scan."""
    suspect_video: str
    total_frames_checked: int = 0
    matched_frames: int = 0
    frame_results: list[FrameMatchResult] = field(default_factory=list)

    @property
    def similarity_percentage(self) -> float:
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

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    # CLIP vectors are naturally dense, normalize to get cosine similarity natively via dot
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0: return 0.0
    return float(np.dot(a, b) / (na * nb))

# ─── Public API ───────────────────────────────────────────────────────────────

def scan_suspect_video(
    suspect_hashes: dict[str, np.ndarray],
    suspect_video_name: str,
    qdrant: QdrantStore,
    threshold: float = MATCH_THRESHOLD_COSINE,
) -> SimilarityReport:
    """Legacy backward compatible scan without speed invariance."""
    return scan_suspect_video_advanced(suspect_hashes, suspect_video_name, qdrant, threshold, speed_invariant=False, temporal_check=False)


def scan_suspect_video_advanced(
    suspect_hashes: dict[str, np.ndarray],
    suspect_video_name: str,
    qdrant: QdrantStore,
    target_clip: str = None,
    threshold: float = MATCH_THRESHOLD_COSINE,
    speed_invariant: bool = True,
    temporal_check: bool = True,
    overlay_tolerance: bool = True,
) -> SimilarityReport:
    """
    Enhanced scan with Vector DB Cosine matching, Speed-invariance on timelines, 
    and Temporal checking.
    """
    report = SimilarityReport(
        suspect_video=suspect_video_name,
        total_frames_checked=len(suspect_hashes),
    )

    sorted_items = sorted(suspect_hashes.items(), key=lambda x: float(x[0]))
    raw_results: list[FrameMatchResult] = []

    # Cache fetched clip timelines to avoid hammering Qdrant
    cached_clip_timelines: dict[str, list[tuple[float, np.ndarray]]] = {}

    for ts_str, embedding in sorted_items:
        suspect_ts = float(ts_str)
        result = FrameMatchResult(suspect_timestamp=suspect_ts, suspect_embedding=embedding)
        
        # 1. Broad Vector Search
        matches = qdrant.search_frame(embedding, limit=5)
        
        if target_clip:
            matches = [m for m in matches if m["clip_name"] == target_clip]
            
        if matches:
            best = matches[0]
            result.best_similarity = best["score"]
            result.matched_clip = best["clip_name"]
            result.matched_timestamp = best["timestamp"]

        # 2. Speed-Invariant Local Timeline Check
        if speed_invariant and result.matched_clip:
            clip_name = result.matched_clip
            if clip_name not in cached_clip_timelines:
                cached_clip_timelines[clip_name] = sorted(
                    qdrant.get_clip_timestamps(clip_name),
                    key=lambda x: x[0]
                )
                
            ts_list = cached_clip_timelines[clip_name]
            
            # For each speed factor, compute the 'expected' timestamp in the source
            for factor in [f for f in SPEED_FACTORS if f != 1.0]:
                adjusted_ts = suspect_ts * factor
                
                # Find nearest DB frame to this adjusted timestamp using binary-ish search or min
                if not ts_list: continue
                nearest_ts, nearest_emb = min(
                    ts_list,
                    key=lambda x: abs(x[0] - adjusted_ts)
                )
                
                # Compute Similarity
                sim = _cosine_sim(embedding, nearest_emb)
                if sim > result.best_similarity:
                    result.best_similarity = sim
                    result.matched_timestamp = nearest_ts

        # 3. Apply Effective Threshold
        eff_threshold = threshold - OVERLAY_THRESHOLD_TOLERANCE if overlay_tolerance else threshold
        if result.best_similarity >= eff_threshold:
            result.is_match = True

        raw_results.append(result)

    # 4. Temporal window validation (Noise Reduction)
    if temporal_check and len(raw_results) >= TEMPORAL_WINDOW:
        validated: list[FrameMatchResult] = []
        n = len(raw_results)
        for i, fr in enumerate(raw_results):
            if fr.is_match:
                window = raw_results[max(0, i-1):min(n, i+2)]
                eff_threshold = threshold - OVERLAY_THRESHOLD_TOLERANCE - 0.1
                neighbour_matches = sum(1 for w in window if w.best_similarity >= eff_threshold)
                
                if neighbour_matches >= 2:
                    validated.append(fr)
                else:
                    fr.is_match = False
                    validated.append(fr)
            else:
                validated.append(fr)
        raw_results = validated

    report.frame_results = raw_results
    report.matched_frames = sum(1 for fr in raw_results if fr.is_match)
    return report
