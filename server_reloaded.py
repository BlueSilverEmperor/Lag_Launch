from __future__ import annotations
print("DEBUG: Loading server.py from:", __file__)

import json
import uuid
import time
import cv2
import threading
import traceback
import datetime as dt
from pathlib import Path
from queue import Queue, Empty

from flask import Flask, jsonify, request, Response, send_from_directory, abort
from flask_cors import CORS

# ─── Core + Pipeline imports ──────────────────────────────────────────────────
from core.hasher import hash_video, extract_frames, FRAME_INTERVAL_SEC
from core.detector import (
    scan_suspect_video,
    scan_suspect_video_advanced,
    load_hash_db,
    MATCH_THRESHOLD,
)
from core.verifier import YOLO_AVAILABLE
from core.discovery import discover_videos
from core.storage import get_storage
from core.compliance import RightsComplianceEngine
from core.rights_gateway import RightsGateway
from core.visual_analyser import VisualAnalyser
from core.zeroday import init_monitor, get_monitor
# ─── Constants & Utilities ──────────────────────────────────────────────────
VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"
}

# Temporary memory to prevent spamming web crawlers with duplicate topics
_SCANNED_TOPICS_CACHE: set[str] = set()

BASE_DIR   = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB_PATH = BASE_DIR / "data" / "hash_db.json"
REPORTS_DIR = BASE_DIR / "reports"

def _load_db(db_path: Path) -> dict:
    return storage.load_all_hashes()

def _save_db(db: dict, db_path: Path) -> None:
    # This was used to save the whole DB. In Mongo we save per clip.
    # But for backward compatibility in the worker, I'll keep the signature
    # or just refactor the worker. Refactoring worker is better.
    pass

# ─── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
CORS(app)

# ─── Job registry ─────────────────────────────────────────────────────────────
storage = get_storage()
# Structure: { job_id: Queue } - metadata is in MongoDB
RUNTIME_QUEUES: dict[str, Queue] = {}
JOBS_LOCK = threading.Lock()

def _new_job(job_type: str) -> tuple[str, dict]:
    job_id = str(uuid.uuid4())
    now = dt.datetime.now()
    job_meta = {
        "id":         job_id,
        "type":       job_type,
        "status":     "running",
        "result":     None,
        "error":      None,
        "created_at": now.isoformat(),
    }
    
    q = Queue()
    with JOBS_LOCK:
        RUNTIME_QUEUES[job_id] = q
        storage.create_job(job_meta)
        storage.prune_jobs(50)
        
    return job_id, job_meta


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"

import re

def _strip_ansi(text: str) -> str:
    # Remove literal escape chars or json-escaped equivalents
    text = str(text)
    ansi_escape = re.compile(r'(\x1B|\u001b|\033)\[[0-9;]*[mGK]')
    text = ansi_escape.sub('', text)
    # Fallback to direct replacement for the known yt-dlp error formats
    return text.replace('[0;31m', '').replace('[0m', '').replace('ERROR:', '').strip()

class ResilientDownloader:
    """
    Handles robust video acquisition from URLs. 
    Downloads to a temp file using fallbacks to avoid empty/failed merges.
    """
    def __init__(self, q: Queue):
        self.q = q
        self.download_dir = DEFAULT_DB_PATH.parent / "downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def log(self, type: str, message: str):
        self.q.put({"type": type, "message": f"[ResilientIO] {message}"})

    def download(self, url: str) -> tuple[Path, str]:
        import yt_dlp
        
        # 1. Attempt best format (may require merging)
        self.log("info", f"Analyzing source: {url[:60]}...")
        
        # Extract metadata first
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            meta = ydl.extract_info(url, download=False)
            title = meta.get('title', 'stream')
            safe_title = "".join([c if c.isalnum() or c in " ._-" else "_" for c in title])
            self.log("info", f"Resolved title: {title}")

        outtmpl = str(self.download_dir / f"%(id)s_{safe_title}.%(ext)s")
        
        # Try best first
        formats = ['best', 'b', 'worst']
        last_err = None
        
        for fmt in formats:
            try:
                self.log("info", f"Downloading using profile: {fmt} ...")
                ydl_opts = {
                    'format': fmt,
                    'outtmpl': outtmpl,
                    'quiet': True,
                    'no_warnings': True,
                    'noprogress': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    path = Path(ydl.prepare_filename(info))
                    
                    if path.exists() and path.stat().st_size > 0:
                        self.log("info", f"Success! Verified {path.stat().st_size / 1024 / 1024:.1f} MB")
                        return path, title
                    else:
                        self.log("warning", f"Format {fmt} produced empty file. Retrying...")
            except Exception as e:
                last_err = str(e)
                self.log("warning", f"Format {fmt} failed: {self._clean_err(e)}")
                
        raise RuntimeError(f"All download formats failed. Last error: {self._clean_err(last_err)}")

    def _clean_err(self, e):
        return _strip_ansi(str(e))

# ─── Background Workers ────────────────────────────────────────────────────────

def _worker_ingest(job_id: str, source: str, interval_sec: float, overwrite: bool, proactive_search: bool = False) -> None:
    q: Queue = RUNTIME_QUEUES.get(job_id)
    if not q: return

    try:
        videos = []
        is_url = source.startswith("http://") or source.startswith("https://")
        
        downloader = ResilientDownloader(q)
        
        if is_url:
            q.put({"type": "info", "message": f"Downloading official clip from URL..."})
            path, title = downloader.download(source)
            videos.append((str(path), title))
        else:
            source_path = Path(source)
            if source_path.is_dir():
                videos = [
                    (str(p), p.name) for p in sorted(source_path.iterdir())
                    if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
                ]
            elif source_path.is_file() and source_path.suffix.lower() in VIDEO_EXTENSIONS:
                videos = [(str(source_path), source_path.name)]
            else:
                raise ValueError(f"Invalid local source: {source}")

        if not videos:
            raise ValueError("No supported video files found.")

        db = storage.load_all_hashes()
        total = len(videos)

        q.put({"type": "start", "total": total,
               "message": f"Found {total} video file(s) — beginning ingestion"})

        ingested = 0
        skipped  = 0

        for i, (stream_url, vid_name) in enumerate(videos):
            q.put({"type": "info", 
                   "message": f"[{i+1}/{len(videos)}] Processing: {vid_name}"})
            
            if vid_name in db and not overwrite:
                q.put({"type": "info", "message": f" -> Skipping (already in DB)"})
                skipped += 1
                continue

            q.put({
                "type": "hashing", "index": i + 1, "total": total,
                "clip": vid_name,
                "message": f"[{i+1}/{total}] Hashing: {vid_name}",
            })

            t0 = time.perf_counter()
            frame_hashes = hash_video(stream_url, interval_sec)
            elapsed = time.perf_counter() - t0

            db[vid_name] = frame_hashes
            storage.save_hashes(vid_name, frame_hashes)
            ingested += 1

            q.put({
                "type": "progress", "index": i + 1, "total": total,
                "clip": vid_name, "frames": len(frame_hashes),
                "elapsed": round(elapsed, 2), "skipped": False,
                "message": f"[{i+1}/{total}] Done: {vid_name} — {len(frame_hashes)} frames ({elapsed:.1f}s)",
            })

            # Proactive Piracy Search
            if proactive_search:
                try:
                    q.put({"type": "info", "message": f"\U0001f916 Starting proactive piracy hunt for: {vid_name}..."})
                    compliance_engine = RightsComplianceEngine(model="deepseek-r1:7b")
                    topics = compliance_engine.extract_topics(vid_name, "")
                    q.put({"type": "info", "message": f"Extracted Search Topics: {', '.join(topics)}"})

                    import asyncio

                    def _emit(ev):
                        """Forward discovery events to the SSE queue."""
                        if ev.get("type") == "discovered":
                            item = ev.get("item", {})
                            # Ensure a URL key exists before saving
                            if item.get("url"):
                                # Override risk level based on verification status
                                if not item.get("is_verified") and (item.get("subscriber_count") or 0) < 50000:
                                    item["risk_level"] = "high"
                                
                                # Track the original source video that triggered this discovery
                                item["source_clip"] = vid_name
                                
                                # Persist to MongoDB
                                try:
                                    storage.save_discovery_result(item)
                                except Exception:
                                    pass
                                q.put({
                                    "type": "discovered",
                                    "item": item,
                                    "message": f"Found: {item.get('title','?')} — {item.get('risk_level','?').upper()} Risk"
                                })
                        elif ev.get("type") == "info":
                            q.put({"type": "info", "message": ev.get("message", "")})

                    for topic in topics[:3]:  # Limit to 3 topics for speed
                        clean_topic = topic.lower().strip()
                        if clean_topic in _SCANNED_TOPICS_CACHE:
                            q.put({"type": "info", "message": f"⏳ Skipping '{topic}' (already searched in recent memory)."})
                            continue
                        
                        _SCANNED_TOPICS_CACHE.add(clean_topic)
                        q.put({"type": "info", "message": f"Searching: '{topic}'..."})
                        # Correctly run the async function in a new event loop
                        loop = asyncio.new_event_loop()
                        try:
                            discovered_items = loop.run_until_complete(
                                discover_videos(topic, emit=_emit)
                            )
                        finally:
                            loop.close()
                        q.put({"type": "info", "message": f"Found {len(discovered_items)} result(s) for '{topic}'."})

                except Exception as e:
                    import traceback
                    q.put({"type": "warning", "message": f"Proactive search error: {str(e)}"})
                    traceback.print_exc()

        result = {
            "total_clips": total,
            "ingested": ingested,
            "skipped": skipped,
            "db_clips": storage.get_hash_count(),
        }
        storage.update_job(job_id, {"status": "done", "result": result})
        q.put({"type": "done", "result": result,
               "message": f"Ingestion complete — {storage.get_hash_count()} clip(s) in DB"})

    except Exception as exc:
        err_msg = _strip_ansi(str(exc))
        storage.update_job(job_id, {"status": "error", "error": err_msg})
        q.put({"type": "error", "message": err_msg, "trace": traceback.format_exc()})


def _worker_scan(
    job_id: str,
    video_path: str,
    threshold: int,
    interval_sec: float,
    run_yolo: bool,
    target_clip: str = None,
    speed_invariant: bool = True,
    temporal_check: bool = True,
    overlay_tolerance: bool = True,
) -> None:
    q: Queue = RUNTIME_QUEUES.get(job_id)
    if not q: return

    try:
        downloader = ResilientDownloader(q)
        is_url = video_path.startswith("http://") or video_path.startswith("https://")
        
        # 1. Start preparation
        if is_url:
            q.put({"type": "info", "message": f"Downloading suspect video from URL..."})
            local_path, vid_name = downloader.download(video_path)
            stream_url = str(local_path)
            # Fetch metadata for AI
            from core.discovery import extract_metadata
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                metadata = loop.run_until_complete(extract_metadata(video_path, "YouTube"))
            finally:
                loop.close()
        else:
            vp = Path(video_path)
            if not vp.is_file():
                raise FileNotFoundError(f"Video file not found: {video_path}")
            stream_url = str(vp)
            vid_name = vp.name
            metadata = {"uploader": "Unknown", "title": vid_name, "platform": "Local"}

        # 2. Initialize AI Modules
        compliance_engine = RightsComplianceEngine(model="deepseek-r1:7b")
        visual_analyser = VisualAnalyser(model="llava")
        rights_gateway = RightsGateway(storage)
        
        source_name = metadata.get("uploader", "Unknown")
        platform = metadata.get("platform", "Unknown")
        reputation = {
            "is_verified": metadata.get("is_verified", False),
            "subscriber_count": metadata.get("subscriber_count"),
            "view_count": metadata.get("view_count", 0)
        }

        # 3. Fast Parallel Pipeline
        from concurrent.futures import ThreadPoolExecutor
        import threading

        meta_topics = []
        compliance_res = {"status": "PENDING", "reason": "Background analysis"}
        visual_desc = ""
        compliance_event = threading.Event()

        def _run_compliance_thread():
            import cv2  # Force import in thread scope
            nonlocal meta_topics, compliance_res, visual_desc
            try:
                # 3.1 Metadata Topics
                meta_topics = compliance_engine.extract_topics(metadata.get("title", ""), "")
                
                # 3.2 Visual Analysis (1 frame)
                cap = cv2.VideoCapture(stream_url)
                if cap.isOpened():
                    # Estimate position
                    total_f = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(total_f * 0.1) if total_f > 0 else 0)
                    ret, frame = cap.read()
                    if ret:
                        visual_desc = visual_analyser.describe_frame(frame)
                    cap.release()
                
                # 3.3 LLM Reasoning
                authorized_publishers = rights_gateway.get_authorized_list_for_llm()
                compliance_res = compliance_engine.check_compliance(
                    meta_topics, visual_desc, reputation, source_name, platform, authorized_publishers
                )
                
                q.put({
                    "type": "compliance_done",
                    "status": compliance_res.get("status"),
                    "reason": compliance_res.get("reason"),
                    "publisher": source_name,
                    "message": f"AI Logic Score: {compliance_res.get('status')}"
                })
            except Exception as e:
                print(f"Compliance Thread Error: {e}")
                traceback.print_exc()
            finally:
                compliance_event.set()

        # Load DB before hashing
        hash_db = storage.load_all_hashes()
        if not hash_db:
            raise RuntimeError("Hash DB is empty — run ingestion first.")
        if target_clip:
            if target_clip not in hash_db:
                raise ValueError(f"Target clip '{target_clip}' not found in database.")
            hash_db = {target_clip: hash_db[target_clip]}

        with ThreadPoolExecutor(max_workers=3) as executor:
            # Task A: Compliance Analysis
            executor.submit(_run_compliance_thread)
            
            # Task B: Hashing & Comparison
            q.put({"type": "phase", "phase": 2, "message": "Phase 2 — Multi-threaded Fingerprinting..."})
            suspect_hashes = hash_video(stream_url, interval_sec)
            
            if not suspect_hashes:
                q.put({"type": "warning", "message": "No frames found in suspect video."})
                report = scan_suspect_video_advanced(
                    {}, vid_name, hash_db, threshold,
                    speed_invariant=speed_invariant,
                    temporal_check=temporal_check,
                    overlay_tolerance=overlay_tolerance,
                )
            else:
                q.put({"type": "hashed", "frames": len(suspect_hashes),
                       "message": f"Hashed {len(suspect_hashes)} frames — running advanced matcher..."})
                report = scan_suspect_video_advanced(
                    suspect_hashes, vid_name, hash_db, threshold,
                    speed_invariant=speed_invariant,
                    temporal_check=temporal_check,
                    overlay_tolerance=overlay_tolerance,
                )
                
            compliance_event.wait(timeout=60)

        q.put({
            "type": "detection_done",
            "matched": report.matched_frames,
            "total": report.total_frames_checked,
            "similarity": report.similarity_percentage,
            "verdict": report.verdict,
            "message": f"Phase 2 Complete: {report.similarity_percentage}% similarity detected."
        })

        # 4. Phase 3: YOLO
        yolo_results = []
        if run_yolo and report.matched_frames > 0:
            if not YOLO_AVAILABLE:
                q.put({"type": "warning", "message": "YOLOv8 not installed — skipping logo verification"})
            else:
                q.put({"type": "phase", "phase": 3, "message": f"Phase 3 — Optimized Logo Verification..."})
                from core.verifier import LogoVerifier
                verifier = LogoVerifier()
                
                # Top 10 capping
                matched_results = [r for r in report.frame_results if r.is_match]
                matched_results.sort(key=lambda x: x.best_distance)
                top_targets = {r.suspect_timestamp for r in matched_results[:10]}

                for ts, frame in extract_frames(stream_url, interval_sec):
                    if round(ts, 2) in top_targets or ts in top_targets:
                        det = verifier.verify_frame(ts, frame)
                        yolo_results.append(det)
                        q.put({
                            "type": "yolo_frame",
                            "timestamp": ts,
                            "logo": det.logo_detected,
                            "confidence": round(det.confidence, 3),
                            "classes": det.detected_classes,
                            "message": f"YOLO @ {ts:.1f}s — {'🚨 Logo detected' if det.logo_detected else '✓ No logo'}"
                        })

        # 5. Final Report Construction
        q.put({"type": "phase", "phase": 4, "message": "Phase 4 — Building Final Report..."})
        yolo_map = {d.timestamp: d for d in yolo_results}

        def _flag(is_match: bool, logo: bool) -> str:
            if is_match and logo: return "CONFIRMED INFRINGEMENT"
            elif is_match:        return "SUSPECTED COPY"
            return "CLEAR"

        def _ts_fmt(s) -> str:
            m, sec = divmod(int(s or 0), 60)
            return f"{m:02d}:{sec:02d}"

        final_frames = []
        for fr in report.frame_results:
            yolo = yolo_map.get(fr.suspect_timestamp)
            logo_det = yolo.logo_detected if yolo else False
            final_frames.append({
                "suspect_timestamp": fr.suspect_timestamp,
                "suspect_time_fmt": _ts_fmt(fr.suspect_timestamp),
                "hamming_distance": fr.best_distance,
                "is_match": fr.is_match,
                "matched_clip": fr.matched_clip,
                "logo_detected": logo_det,
                "flag_status": _flag(fr.is_match, logo_det),
            })

        # Persist to MongoDB
        ts_str = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"{vid_name}_{ts_str}_report.json"
        
        final_report_data = {
            "report_filename":       report_filename,
            "suspect_video":         vid_name,
            "total_frames_checked":  report.total_frames_checked,
            "matched_frames":        report.matched_frames,
            "similarity_percentage": report.similarity_percentage,
            "logo_confirmations":    sum(1 for d in yolo_results if d.logo_detected),
            "verdict":               report.verdict,
            "compliance_status":     compliance_res.get("status"),
            "compliance_reason":     compliance_res.get("reason"),
            "publisher":             source_name,
            "topics":                meta_topics,
            "frames":                final_frames,
            "generated_at":          dt.datetime.now().isoformat()
        }
        storage.save_report(final_report_data)

        q.put({
            "type": "done",
            "result": final_report_data,
            "report_url": f"/api/reports/{report_filename}",
            "message": f"Scan complete. Verdict: {report.verdict}"
        })

    except Exception as e:
        q.put({"type": "error", "message": f"Pipeline Error: {str(e)}"})
        traceback.print_exc()


def _worker_auto_ingest(job_id: str, topic: str, auto_scan: bool) -> None:
    q: Queue = RUNTIME_QUEUES.get(job_id)
    if not q: return
    
    try:
        q.put({"type": "start", "message": f"Starting Auto Ingestion for topic: '{topic}'"})
        
        def emit_cb(msg):
            q.put(msg)
            
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(discover_videos(topic, emit_cb))
        loop.close()
        
        high_risk_urls = [r["url"] for r in results if r["risk_level"] == "high" and r["url"]]
        
        q.put({
            "type": "phase", "phase": 2, 
            "message": f"Discovery found {len(results)} links ({len(high_risk_urls)} high-risk)"
        })
        
        if auto_scan and high_risk_urls:
            q.put({"type": "info", "message": f"Auto-scanning {len(high_risk_urls)} high-risk links..."})
            for idx, url in enumerate(high_risk_urls):
                q.put({"type": "info", "message": f"--- Sending to Scan Pipeline: {url} ---"})
                try:
                    # Leverage the generic scan worker by firing a new job
                    # Or do it inline. Let's do it via new job invocation on DB
                    scan_job_id, _ = _new_job("scan")
                    t = threading.Thread(
                        target=_worker_scan,
                        args=(scan_job_id, url, MATCH_THRESHOLD, FRAME_INTERVAL_SEC, True),
                        daemon=True
                    )
                    t.start()
                    q.put({"type": "info", "message": f"Started background scan job: {scan_job_id}"})
                except Exception as e:
                    q.put({"type": "warning", "message": f"Failed to queue {url}: {e}"})

        storage.update_job(job_id, {"status": "done", "result": results})
        q.put({
            "type": "done",
            "result": results,
            "message": "Auto Ingestion complete!"
        })

    except Exception as exc:
        err_msg = _strip_ansi(str(exc))
        storage.update_job(job_id, {"status": "error", "error": err_msg})
        q.put({"type": "error", "message": err_msg, "trace": traceback.format_exc()})


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/status")
def api_status():
    db_clips = storage.get_hash_count()
    # For total frames we still need to load all or add a new storage method
    # Let's just load all for now as it's not huge
    all_hashes = storage.load_all_hashes()
    total_frames = sum(len(v) for v in all_hashes.values())
    report_count = storage.get_report_count()
    running_jobs = storage.get_running_job_count()

    return jsonify({
        "db_clips":     db_clips,
        "total_frames": total_frames,
        "report_count": report_count,
        "running_jobs": running_jobs,
        "yolo_available": YOLO_AVAILABLE,
        "db_path":      "MongoDB (dap_db)",
    })


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    body        = request.get_json(force=True, silent=True) or {}
    source      = body.get("source", "")
    interval    = float(body.get("interval", FRAME_INTERVAL_SEC))
    overwrite   = bool(body.get("overwrite", False))
    proactive   = bool(body.get("proactive_search", False))

    if not source:
        return jsonify({"error": "source is required"}), 400

    job_id, _ = _new_job("ingest")
    t = threading.Thread(
        target=_worker_ingest,
        args=(job_id, source, interval, overwrite, proactive),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/scan", methods=["POST"])
def api_scan():
    body           = request.get_json(force=True, silent=True) or {}
    video_path     = body.get("video_path", "")
    threshold      = int(body.get("threshold", MATCH_THRESHOLD))
    interval       = float(body.get("interval", FRAME_INTERVAL_SEC))
    run_yolo       = bool(body.get("run_yolo", True))
    target_clip    = body.get("target_clip", None)
    speed_inv      = bool(body.get("speed_invariant", True))
    temporal_chk   = bool(body.get("temporal_check", True))
    overlay_tol    = bool(body.get("overlay_tolerance", True))

    if not video_path:
        return jsonify({"error": "video_path is required"}), 400

    job_id, _ = _new_job("scan")
    t = threading.Thread(
        target=_worker_scan,
        args=(job_id, video_path, threshold, interval, run_yolo, target_clip,
              speed_inv, temporal_chk, overlay_tol),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/auto_ingest", methods=["POST"])
def api_auto_ingest():
    body = request.get_json(force=True, silent=True) or {}
    topic = body.get("topic", "")
    auto_scan = bool(body.get("auto_scan", True))

    if not topic:
        return jsonify({"error": "topic is required"}), 400

    job_id, _ = _new_job("auto_ingest")
    t = threading.Thread(
        target=_worker_auto_ingest,
        args=(job_id, topic, auto_scan),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/stream/<job_id>")
def api_stream(job_id: str):
    job = storage.get_job(job_id)
    if not job:
        abort(404)

    def generate():
        q: Queue = RUNTIME_QUEUES.get(job_id)
        if not q:
            # If job is already done, send result and close
            if job["status"] in ("done", "error"):
                 yield _sse({"type": job["status"], "result": job.get("result"), "message": "Job already completed."})
            return

        # Send initial heartbeat
        yield _sse({"type": "connected", "job_id": job_id})

        while True:
            try:
                event = q.get(timeout=0.4)
                yield _sse(event)
                if event.get("type") in ("done", "error"):
                    break
            except Empty:
                # Refresh job status from storage
                current_job = storage.get_job(job_id)
                if current_job["status"] in ("done", "error"):
                    break
                yield ": heartbeat\n\n"   # SSE comment keeps connection alive
        
        # Clean up queue
        with JOBS_LOCK:
            RUNTIME_QUEUES.pop(job_id, None)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/jobs")
def api_jobs():
    jobs = storage.list_jobs(50)
    return jsonify(jobs)


@app.route("/api/reports")
def api_reports():
    reports = storage.list_reports(100)
    # Map fields for UI compatibility
    out = []
    for r in reports:
        out.append({
            "filename":   r.get("report_filename", "unnamed.json"),
            "suspect":    r.get("suspect_video", "unknown"),
            "similarity": r.get("similarity_percentage", 0),
            "verdict":    r.get("verdict", ""),
            "generated":  r.get("generated_at", ""),
            "frames":     r.get("total_frames_checked", 0),
            "matched":    r.get("matched_frames", 0),
        })
    return jsonify(out)


@app.route("/api/reports/<filename>")
def api_report_detail(filename: str):
    report = storage.get_report(filename)
    if not report:
        abort(404)
    return jsonify(report)


@app.route("/api/db", methods=["GET"])
def api_db_info():
    db = storage.load_all_hashes()
    clips = [
        {"name": name, "frames": len(hashes)}
        for name, hashes in db.items()
    ]
    return jsonify({"clips": clips, "total_clips": len(clips)})


@app.route("/api/compliance/authorized", methods=["GET", "POST"])
def api_auth_manager():
    if request.method == "GET":
        return jsonify(storage.list_authorized_publishers())

    body        = request.get_json(force=True, silent=True) or {}
    name        = body.get("name")
    platform    = body.get("platform")
    channel_url = body.get("channel_url", "")
    if not name or not platform:
        return jsonify({"error": "name and platform are required"}), 400
    storage.add_authorized_publisher(name, platform, channel_url)
    return jsonify({"message": f"Added {name} on {platform} to authorized list."})


@app.route("/api/compliance/authorized/<int:pub_id>", methods=["DELETE"])
def api_delete_authorized(pub_id: int):
    storage.remove_authorized_publisher(pub_id)
    return jsonify({"message": "Publisher removed from authorized list."})


@app.route("/api/discovery/results", methods=["GET"])
def api_discovery_results():
    return jsonify(storage.list_discovery_results())


@app.route("/api/zeroday/status", methods=["GET"])
def api_zeroday_status():
    mon = get_monitor()
    return jsonify({"running": mon.is_running if mon else False})


@app.route("/api/zeroday/start", methods=["POST"])
def api_zeroday_start():
    mon = get_monitor()
    if not mon:
        return jsonify({"error": "Monitor not initialised"}), 500
    if mon.is_running:
        return jsonify({"message": "0-Day Monitor already running"})
    mon.start()
    return jsonify({"message": "0-Day Monitor started"})


@app.route("/api/zeroday/stop", methods=["POST"])
def api_zeroday_stop():
    mon = get_monitor()
    if mon:
        mon.stop()
    return jsonify({"message": "0-Day Monitor stopped"})


@app.route("/api/db", methods=["DELETE"])
def api_db_clear():
    storage.clear_hashes()
    return jsonify({"message": "Hash database cleared from MongoDB."})


def _migrate_data():
    """Migrate existing JSON and MySQL data to MongoDB if it exists."""
    print("Checking for legacy data to migrate to MongoDB...")
    
    # 1. Migrate from JSON (Legacy v1/v2)
    if DEFAULT_DB_PATH.exists():
        try:
            with open(DEFAULT_DB_PATH, "r") as f:
                db = json.load(f)
            count = 0
            for vid_name, hashes in db.items():
                storage.save_hashes(vid_name, hashes)
                count += 1
            print(f"Migrated {count} clips from JSON to MongoDB.")
            bak = DEFAULT_DB_PATH.with_suffix(".json.bak")
            DEFAULT_DB_PATH.rename(bak)
        except Exception as e:
            print(f"JSON Hash migration failed: {e}")

    # 2. Migrate from MySQL (Legacy v3.0m)
    try:
        import mysql.connector
        cnx = mysql.connector.connect(host="localhost", user="root", password="Sridhar1234$", database="dap_db")
        cursor = cnx.cursor(dictionary=True)
        
        # Migrate Clips & Hashes
        cursor.execute("SELECT id, name FROM clips")
        clips = cursor.fetchall()
        for c in clips:
            cursor.execute("SELECT timestamp, hash_hex FROM hashes WHERE clip_id = %s", (c["id"],))
            rows = cursor.fetchall()
            h_map = {str(r["timestamp"]): r["hash_hex"] for r in rows}
            storage.save_hashes(c["name"], h_map)
        
        # Migrate Reports
        cursor.execute("SELECT full_data FROM reports")
        reports = cursor.fetchall()
        for r in reports:
            if r["full_data"]:
                data = json.loads(r["full_data"])
                storage.save_report(data)
        
        # Migrate Auth Publishers
        cursor.execute("SELECT name, platform FROM authorized_publishers")
        pubs = cursor.fetchall()
        for p in pubs:
            storage.add_authorized_publisher(p["name"], p["platform"])
            
        print(f"Successfully migrated data from MySQL to MongoDB.")
        cursor.close()
        cnx.close()
        
        # Optionally drop MySQL DB or rename to indicate it's dead
        # For safety we just leave it for now.
    except Exception as e:
        # If MySQL isn't running or db doesn't exist, this is expected for new installs
        print(f"MySQL migration skipped or failed (likely not present): {e}")

    # 3. Migrate Reports from Disk
    if REPORTS_DIR.exists():
        try:
            reports = list(REPORTS_DIR.glob("*.json"))
            count = 0
            for p in reports:
                if "backup" in str(p): continue
                with open(p, "r") as f:
                    data = json.load(f)
                data["report_filename"] = p.name
                storage.save_report(data)
                bak_dir = REPORTS_DIR / "backup"
                bak_dir.mkdir(exist_ok=True)
                p.rename(bak_dir / p.name)
                count += 1
            if count > 0:
                print(f"Migrated {count} reports from disk to MongoDB.")
        except Exception as e:
            print(f"Report disk migration failed: {e}")

def init_app():
    """Initialize storage and migrate data."""
    _migrate_data()
    
    # Initialize 0-Day Monitor
    init_monitor(storage, hash_video)
    get_monitor().start()
    
    print("Database initialized.")

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║  DAP Server v3.0m • http://127.0.0.1:9000    ║")
    print("  ╚══════════════════════════════════════════════╝\n")
    
    init_app()
    app.run(host="0.0.0.0", port=9000, debug=False, threaded=True)
