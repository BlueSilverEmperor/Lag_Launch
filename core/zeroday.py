"""
core/zeroday.py
---------------
0-Day Hashing Monitor for Authorized Content.

Continuously polls authorized publisher channels (YouTube, etc.)
for new uploads and auto-ingests them the moment they appear —
before any piracy can occur.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp


class ZeroDayMonitor:
    """Background service that watches authorized channels for new content."""

    def __init__(
        self,
        storage,
        hash_fn: Callable,
        interval_sec: float = 2.0,
        poll_interval: int = 300,   # Check every 5 minutes
    ):
        self.storage = storage
        self.hash_fn = hash_fn
        self.interval_sec = interval_sec
        self.poll_interval = poll_interval

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_event: Optional[Callable] = None

        # URLs already hashed — prevent re-processing
        self._known_urls: set[str] = set()
        self._load_known_urls()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_known_urls(self):
        try:
            self._known_urls = set(self.storage.list_monitored_urls())
        except Exception:
            self._known_urls = set()

    def _emit(self, msg_type: str, message: str, **extra):
        if self._on_event:
            try:
                self._on_event({"type": msg_type, "message": message, **extra})
            except Exception:
                pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, on_event: Optional[Callable] = None):
        if self._running:
            return
        self._running = True
        self._on_event = on_event
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ZeroDayMonitor")
        self._thread.start()
        self._emit("info", "0-Day Monitor started. Watching authorized channels...")

    def stop(self):
        self._running = False
        self._emit("info", "0-Day Monitor stopped.")

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run_loop(self):
        while self._running:
            try:
                self._poll_all_channels()
            except Exception as e:
                self._emit("warning", f"0-Day: Poll cycle error: {e}")
            # Sleep in small chunks so stop() responds quickly
            for _ in range(self.poll_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _poll_all_channels(self):
        publishers = self.storage.list_authorized_publishers()
        channels = [p for p in publishers if p.get("channel_url")]

        if not channels:
            self._emit("info", "0-Day: No monitored channels configured. Add channel URLs to authorized publishers.")
            return

        for pub in channels:
            if not self._running:
                break
            try:
                self._emit("info", f"0-Day: Checking [{pub['name']}] for new uploads...")
                new_videos = self._fetch_latest_videos(pub["channel_url"], limit=3)
                for video in new_videos:
                    url = video.get("url", "")
                    if url and url not in self._known_urls:
                        self._emit("info", f"0-Day: 🆕 New content detected: {video['title']}")
                        try:
                            self._ingest_video(video)
                            self._known_urls.add(url)
                            self.storage.add_monitored_url(url)
                        except Exception as e:
                            self._emit("warning", f"0-Day: Ingest failed for '{video['title']}': {e}")
            except Exception as e:
                self._emit("warning", f"0-Day: Error checking '{pub.get('name', '?')}': {e}")

    def _fetch_latest_videos(self, channel_url: str, limit: int = 3) -> list[dict]:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlistend": limit,
        }
        results = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if info and "entries" in info:
                for entry in (info.get("entries") or [])[:limit]:
                    if not entry:
                        continue
                    vid_id = entry.get("id", "")
                    url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else entry.get("url", "")
                    if url:
                        results.append({"url": url, "title": entry.get("title", "Unknown")})
        return results

    def _ingest_video(self, video: dict):
        """Download, hash, and store a newly detected official video."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="dap_zeroday_"))
        ydl_opts = {
            "format": "best[height<=720]/best",
            "quiet": True,
            "no_warnings": True,
            "outtmpl": str(tmp_dir / "%(title)s.%(ext)s"),
            "noplaylist": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video["url"], download=True)
                filepath = Path(ydl.prepare_filename(info))

                # Find downloaded file (ext may vary)
                candidates = list(tmp_dir.glob("*"))
                if not candidates:
                    raise FileNotFoundError("Download produced no file")
                filepath = max(candidates, key=lambda p: p.stat().st_size)

                hashes = self.hash_fn(str(filepath), self.interval_sec)
                title = video["title"]
                
                # Push vectors to Qdrant
                from .qdrant_store import QdrantStore
                qdrant = QdrantStore()
                qdrant.insert_hashes(title, hashes)
                
                self._emit(
                    "progress",
                    f"0-Day: ✓ Hashed & stored '{title}' ({len(hashes)} frames)",
                    clip=title,
                    frames=len(hashes),
                    index=1,
                    total=1,
                )
        finally:
            # Clean up temp files
            import shutil
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


# ── Global singleton ─────────────────────────────────────────────────────────

_monitor: Optional[ZeroDayMonitor] = None


def get_monitor() -> Optional[ZeroDayMonitor]:
    return _monitor


def init_monitor(storage, hash_fn, interval_sec: float = 2.0, poll_interval: int = 300) -> ZeroDayMonitor:
    global _monitor
    _monitor = ZeroDayMonitor(storage, hash_fn, interval_sec, poll_interval)
    return _monitor
