from __future__ import annotations
print("DEBUG: Loading server_reloaded.py from:", __file__)

from dotenv import load_dotenv
load_dotenv()

import json
import uuid
import time
import cv2
import threading
import traceback
import datetime as dt
from queue import Empty
from pathlib import Path
import re

def sanitize_filename(name: str) -> str:
    """Removes or replaces characters that are illegal in Windows/Linux filenames."""
    if not name: return "unknown_video"
    # Replace illegal characters with underscores
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    return clean.strip()[:150]

from flask import Flask, jsonify, request, Response, send_from_directory, abort
from flask_cors import CORS

# ─── Core + Pipeline imports ──────────────────────────────────────────────────
# Upgraded background task queue (fixes deadlocks)
from core.queue import get_queue
# Replaces imagehash with CLIP+Qdrant
from core.hasher import hash_video, extract_frames, FRAME_INTERVAL_SEC
from core.qdrant_store import QdrantStore
from core.detector import (
    scan_suspect_video_advanced,
    MATCH_THRESHOLD_COSINE,
)
from core.verifier import YOLO_AVAILABLE
from core.discovery import discover_videos
from core.storage import get_storage
from core.rights_gateway import RightsGateway
from core.zeroday import init_monitor, get_monitor
from core.heatmap import generate_similarity_heatmap
from core.dmca_generator import generate_dmca_text, save_dmca, save_dmca_pdf
from core.security import ApplicationFirewall
from core.ai_engine import AIEngine

ai_engine = AIEngine()

# ─── Constants & Utilities ──────────────────────────────────────────────────
VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"
}

_SCANNED_TOPICS_CACHE: set[str] = set()

BASE_DIR   = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB_PATH = BASE_DIR / "data" / "hash_db.json"
REPORTS_DIR = BASE_DIR / "reports"

from flask_cors import CORS
from flask import Flask, request, jsonify, abort, Response, send_from_directory

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
CORS(app)

from core.storage import get_storage
storage  = get_storage()
firewall = ApplicationFirewall()

storage = get_storage()
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
    with JOBS_LOCK:
        get_queue().get_bus(job_id) # init IPC queue
        storage.create_job(job_meta)
        storage.prune_jobs(50)
    return job_id, job_meta

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"

import re

def _strip_ansi(text: str) -> str:
    text = str(text)
    ansi_escape = re.compile(r'(\x1B|\u001b|\033)\[[0-9;]*[mGK]')
    text = ansi_escape.sub('', text)
    return text.replace('[0;31m', '').replace('[0m', '').replace('ERROR:', '').strip()

class ResilientDownloader:
    def __init__(self, q):
        self.q = q
        self.download_dir = DEFAULT_DB_PATH.parent / "downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def log(self, type: str, message: str):
        self.q.put({"type": type, "message": f"[ResilientIO] {message}"})

    def download(self, url: str) -> tuple[Path, str]:
        import yt_dlp
        self.log("info", f"Analyzing source: {url[:60]}...")
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            meta = ydl.extract_info(url, download=False)
            title = meta.get('title', 'stream')
            safe_title = "".join([c if c.isalnum() or c in " ._-" else "_" for c in title])
            self.log("info", f"Resolved title: {title}")

        outtmpl = str(self.download_dir / f"%(id)s_{safe_title}.%(ext)s")
        formats = ['best', 'b', 'worst']
        last_err = None
        for fmt in formats:
            try:
                self.log("info", f"Downloading using profile: {fmt} ...")
                ydl_opts = {'format': fmt, 'outtmpl': outtmpl, 'quiet': True, 'no_warnings': True, 'noprogress': True}
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

    def get_meta(self, url: str, timeout: float = 30.0):
        """Pre-fetch metadata with a strict timeout to avoid worker hang."""
        import yt_dlp
        import concurrent.futures
        
        def _fetch():
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                return ydl.extract_info(url, download=False)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise RuntimeError(f"Metadata extraction timed out after {timeout}s")

# ─── Background Workers ────────────────────────────────────────────────────────

def _worker_ingest(q, job_id: str, source: str, interval_sec: float, overwrite: bool, proactive_search: bool = False):
    q.put({"type": "info", "message": "🚀 Ingestion worker initialized."})
    storage = get_storage()
    qdrant = QdrantStore()

    try:
        
        videos = []
        is_url = (isinstance(source, str) and (source.startswith("http://") or source.startswith("https://")))
        downloader = ResilientDownloader(q)
        
        if is_url:
            # Emit start EARLY for URLs so the UI doesn't hang on "Starting..."
            q.put({"type": "start", "total": 1, "message": "Analyzing remote source..."})
            try:
                meta = downloader.get_meta(source, timeout=30.0)
                title = meta.get('title', 'stream')
                q.put({"type": "info", "message": f"Source verified: {title}"})
                path, title = downloader.download(source)
                videos.append((str(path), title))
            except Exception as de:
                q.put({"type": "error", "message": f"Initial download failed: {de}"})
                return
        else:
            source_path = Path(source)
            if source_path.is_dir():
                videos = [(str(p), p.name) for p in sorted(source_path.iterdir()) if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
            elif source_path.is_file() and source_path.suffix.lower() in VIDEO_EXTENSIONS:
                videos = [(str(source_path), source_path.name)]
            
            if not videos:
                raise ValueError("No supported video files found in source path.")
                
            total = len(videos)
            q.put({"type": "start", "total": total, "message": f"Found {total} local video(s) — beginning ingestion"})

        total = len(videos)
        if total == 0: return

        ingested = 0
        skipped  = 0

        for i, (stream_url, vid_name) in enumerate(videos):
            q.put({"type": "info", "message": f"[{i+1}/{total}] Processing: {vid_name}"})
            
            # Using Hash extraction + Qdrant insertion
            q.put({"type": "hashing", "index": i + 1, "total": total, "clip": vid_name, "message": f"[{i+1}/{total}] Abstracting CLIP embeddings: {vid_name}"})
            t0 = time.perf_counter()
            frame_embeddings = hash_video(stream_url, interval_sec)
            elapsed = time.perf_counter() - t0

            qdrant.insert_hashes(vid_name, frame_embeddings)
            
            # Synchronize metadata to MongoDB for dashboard visibility
            try:
                # We store a "summary" in Mongo for the dashboard clip list
                storage.clips.update_one(
                    {"name": vid_name},
                    {"$set": {
                        "name": vid_name,
                        "frames": len(frame_embeddings),
                        "updated_at": dt.datetime.now()
                    }},
                    upsert=True
                )
            except Exception as me:
                q.put({"type": "warning", "message": f"Failed to sync metadata to Mongo: {me}"})

            ingested += 1

            q.put({
                "type": "progress", "index": i + 1, "total": total, "clip": vid_name, "frames": len(frame_embeddings),
                "elapsed": round(elapsed, 2), "skipped": False,
                "message": f"[{i+1}/{total}] Done: {vid_name} — {len(frame_embeddings)} frames -> Qdrant ({elapsed:.1f}s)",
            })

            if proactive_search:
                import asyncio
                from core.discovery import discover_videos
                q.put({"type": "info", "message": f"\U0001f916 Starting proactive piracy hunt for: {vid_name}..."})
                
                # Topic extraction restored via AIEngine (Google AI Ready)
                topics = ai_engine.get_topics(vid_name)
                q.put({"type": "info", "message": f"AI Engine ({ai_engine.mode}): Extracted {len(topics)} topics."})

                def _emit(ev):
                    if ev.get("type") == "discovered":
                        item = ev.get("item", {})
                        if item.get("url"):
                            item["source_clip"] = vid_name
                            try: storage.save_discovery_result(item)
                            except Exception: pass
                            q.put({"type": "discovered", "item": item, "message": f"Found: {item.get('title','?')} — {item.get('risk_level','?').upper()} Risk"})
                    elif ev.get("type") == "info":
                        q.put({"type": "info", "message": ev.get("message", "")})

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    q.put({"type": "info", "message": f"🚀 Launching Persistent Discovery Cluster ({len(topics)} topics)..."})
                    # Allow up to 3 topics for exhaustive coverage
                    discovery_tasks = [discover_videos(topic, emit=_emit) for topic in topics[:3]]
                    
                    # REMOVED TIMEOUT: Let it run until completion as requested
                    loop.run_until_complete(asyncio.gather(*discovery_tasks))
                    
                    q.put({"type": "info", "message": "✅ Discovery Cluster synchronized."})
                except Exception as de:
                    q.put({"type": "warning", "message": f"❌ Discovery Cluster error: {de}"})
                finally:
                    loop.close()
            
            if is_url:
                try:
                    Path(stream_url).unlink(missing_ok=True)
                    q.put({"type": "info", "message": f"Cleaned up temp video: {vid_name}"})
                except Exception: pass

        result = {
            "total_clips": total, "ingested": ingested, "skipped": skipped,
            "db_clips": qdrant.count_frames(),
        }
        storage.update_job(job_id, {"status": "done", "result": result})
        q.put({"type": "done", "result": result, "message": f"Ingestion complete — {qdrant.count_frames()} frames in Vector DB"})

    except Exception as exc:
        err_msg = _strip_ansi(str(exc))
        storage.update_job(job_id, {"status": "error", "error": err_msg})
        q.put({"type": "error", "message": err_msg, "trace": traceback.format_exc()})


def _worker_scan(q, job_id: str, video_path: str, threshold: float, interval_sec: float, run_yolo: bool, target_clip: str = None, speed_invariant: bool = True, temporal_check: bool = True, overlay_tolerance: bool = True):
    from core.storage import get_storage
    storage = get_storage()
    qdrant = QdrantStore()

    try:
        downloader = ResilientDownloader(q)
        is_url = video_path.startswith("http://") or video_path.startswith("https://")
        
        if is_url:
            q.put({"type": "info", "message": f"Downloading suspect video from URL..."})
            local_path, vid_name = downloader.download(video_path)
            stream_url = str(local_path)
            from core.discovery import extract_metadata
            import asyncio
            loop = asyncio.new_event_loop()
            metadata = loop.run_until_complete(extract_metadata(video_path, "YouTube"))
            loop.close()
        else:
            vp = Path(video_path)
            if not vp.is_file(): raise FileNotFoundError(f"Video file not found: {video_path}")
            stream_url = str(vp)
            vid_name = vp.name
            metadata = {"uploader": "Unknown", "title": vid_name, "platform": "Local"}

        rights_gateway = RightsGateway(storage)
        source_name = metadata.get("uploader", "Unknown")
        
        q.put({"type": "phase", "phase": 2, "message": "Phase 2 — Multi-threaded Vector Fingerprinting..."})
        suspect_hashes = hash_video(stream_url, interval_sec)
        
        if not suspect_hashes:
            q.put({"type": "warning", "message": "No frames found in suspect video."})
            return

        q.put({"type": "hashed", "frames": len(suspect_hashes), "message": f"Hashed {len(suspect_hashes)} frames -> Running Qdrant Search..."})
        report = scan_suspect_video_advanced(suspect_hashes, vid_name, qdrant, target_clip, threshold, speed_invariant, temporal_check, overlay_tolerance)

        q.put({
            "type": "detection_done", "matched": report.matched_frames, "total": report.total_frames_checked,
            "similarity": report.similarity_percentage, "verdict": report.verdict,
            "message": f"Phase 2 Complete: {report.similarity_percentage}% similarity detected."
        })

        yolo_results = []
        if run_yolo and report.matched_frames > 0:
            if not YOLO_AVAILABLE:
                q.put({"type": "warning", "message": "YOLOv8 not installed — skipping logo verification"})
            else:
                q.put({"type": "phase", "phase": 3, "message": f"Phase 3 — Optimized Logo Verification..."})
                from core.verifier import LogoVerifier
                verifier = LogoVerifier()
                
                # Limit YOLO to top 5 hits visually (remediation requested)
                matched_results = [r for r in report.frame_results if r.is_match]
                matched_results.sort(key=lambda x: x.best_similarity, reverse=True)
                top_targets = {r.suspect_timestamp for r in matched_results[:5]}

                for ts, frame in extract_frames(stream_url, interval_sec, use_scene_detection=False):
                    if ts in top_targets or round(ts, 2) in top_targets:
                        det = verifier.verify_frame(ts, frame)
                        yolo_results.append(det)
                        q.put({"type": "yolo_frame", "timestamp": ts, "logo": det.logo_detected, "confidence": round(det.confidence, 3), "classes": det.detected_classes, "message": f"YOLO @ {ts:.1f}s — {'🚨 Logo detected' if det.logo_detected else '✓ No logo'}"})

        q.put({"type": "phase", "phase": 4, "message": "Phase 4 — Building Dynamic Report & DB Entries..."})
        yolo_map = {d.timestamp: d for d in yolo_results}
        
        def _ts_fmt(s): m, sec = divmod(int(s or 0), 60); return f"{m:02d}:{sec:02d}"
        
        def _flag(is_match: bool, logo: bool) -> str:
            if is_match and logo: return "SUSPECTED INFRINGEMENT"
            elif is_match:        return "SIMILAR CONTENT"
            return "CLEAR"

        final_frames = []
        for fr in report.frame_results:
            yolo = yolo_map.get(fr.suspect_timestamp)
            logo_det = yolo.logo_detected if yolo else False
            final_frames.append({
                "suspect_timestamp": fr.suspect_timestamp,
                "suspect_time_fmt": _ts_fmt(fr.suspect_timestamp),
                "similarity_score": fr.best_similarity,
                "is_match": fr.is_match,
                "matched_clip": fr.matched_clip,
                "logo_detected": logo_det,
                "flag_status": _flag(fr.is_match, logo_det)
            })

        # Generate Visual Match Heatmap
        ts_list = [f["suspect_timestamp"] for f in final_frames]
        sims_list = [f["similarity_score"] for f in final_frames]
        flags_list = [f["is_match"] for f in final_frames]
        heatmap_b64 = generate_similarity_heatmap(ts_list, sims_list, flags_list)
        
        ts_str = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_vid_name = sanitize_filename(vid_name)
        report_filename = f"{safe_vid_name}_{ts_str}_report.json"
        
        # DMCA Takedown Generation
        dmca_text = None
        if report.similarity_percentage >= 10:
             evidence_ts = [f["suspect_time_fmt"] for f in final_frames if f["is_match"]]
             dmca_text = generate_dmca_text(
                 vid_name, source_name, report.matched_frames, report.total_frames_checked, 
                 report.similarity_percentage, evidence_ts, 
                 infringing_url=video_path,
                 contact_name="Lag_Launch Rights Enforcement",
                 contact_email="legal@laglaunch.com",
                 contact_address="123 Security Blvd, Cyber City"
             )
             save_dmca(report_filename, dmca_text, BASE_DIR)
             save_dmca_pdf(report_filename, dmca_text, BASE_DIR)

        final_report_data = {
            "report_filename": report_filename,
            "suspect_video": vid_name, "total_frames_checked": report.total_frames_checked,
            "matched_frames": report.matched_frames, "similarity_percentage": report.similarity_percentage,
            "verdict": report.verdict, "publisher": source_name,
            "logo_confirmations": sum(1 for d in yolo_results if d.logo_detected),
            "heatmap_base64": heatmap_b64,
            "dmca_generated": bool(dmca_text),
            "dmca_pdf_available": bool(dmca_text),
            "frames": final_frames, "generated_at": dt.datetime.now().isoformat()
        }
        storage.save_report(final_report_data)

        q.put({"type": "done", "result": final_report_data, "report_url": f"/api/reports/{report_filename}", "message": f"Scan complete. Verdict: {report.verdict}"})
    except Exception as e:
        q.put({"type": "error", "message": f"Pipeline Error: {str(e)}"})
        traceback.print_exc()
    finally:
        if is_url and 'stream_url' in locals():
            try:
                Path(stream_url).unlink(missing_ok=True)
                q.put({"type": "info", "message": f"Cleaned up suspect video: {vid_name}"})
            except Exception: pass

def _worker_auto_ingest(q, job_id: str, topic: str, auto_scan: bool):
    from core.storage import get_storage
    storage = get_storage()
    
    try:
        q.put({"type": "start", "message": f"Starting Auto Ingestion for topic: '{topic}'"})
        def emit_cb(msg): q.put(msg)
        import asyncio
        loop = asyncio.new_event_loop()
        results = loop.run_until_complete(discover_videos(topic, emit_cb))
        loop.close()
        
        high_risk_urls = [r["url"] for r in results if r["risk_level"] == "high" and r["url"]]
        q.put({"type": "phase", "phase": 2, "message": f"Discovery found {len(results)} links ({len(high_risk_urls)} high-risk)"})
        
        if auto_scan and high_risk_urls:
            q.put({"type": "info", "message": f"Auto-scanning {len(high_risk_urls)} high-risk links..."})
            for u in high_risk_urls:
                scan_job_id, _ = _new_job("scan")
                get_queue().enqueue(scan_job_id, _worker_scan, u, MATCH_THRESHOLD_COSINE, FRAME_INTERVAL_SEC, True)
                q.put({"type": "info", "message": f"Queued auto-scan: {scan_job_id} for URL: {u[:30]}..."})
                
        q.put({"type": "done", "message": f"Discovery cycle complete. Found {len(results)} results ({len(high_risk_urls)} high-risk).", "result": results})
        storage.update_job(job_id, {"status": "completed", "completed_at": dt.datetime.now()})
    except Exception as exc:
        err_msg = str(exc)
        storage.update_job(job_id, {"status": "failed", "completed_at": dt.datetime.now()})
        q.put({"type": "error", "message": err_msg})

# ─── Routes ───────────────────────────────────────────────────────────────────

# --- Security Middleware (Application Firewall) ---
@app.before_request
def security_filter():
    is_ok, msg = firewall.validate_request(request.remote_addr)
    if not is_ok:
        abort(403, description=msg)

@app.after_request
def security_headers(response):
    return firewall.apply_security_headers(response)

@app.route("/")
def index(): return send_from_directory(STATIC_DIR, "index.html")

@app.route("/api/status")
def api_status():
    report_count = storage.get_report_count()
    running_jobs = storage.get_running_job_count()
    try:
        qdrant = QdrantStore()
        total_frames = qdrant.count_frames()
    except Exception:
        total_frames = 0

    return jsonify({
        "db_clips": storage.get_hash_count(), "total_frames": total_frames,
        "report_count": report_count, "running_jobs": running_jobs,
        "yolo_available": YOLO_AVAILABLE, "db_path": "Qdrant (Vector DB)",
    })

@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    body = request.get_json(force=True, silent=True) or {}
    source = body.get("source", "")
    interval = float(body.get("interval", FRAME_INTERVAL_SEC))
    overwrite = bool(body.get("overwrite", False))
    proactive = bool(body.get("proactive_search", False))
    if not source: return jsonify({"error": "source is required"}), 400
    job_id, _ = _new_job("ingest")
    get_queue().enqueue(job_id, _worker_ingest, source, interval, overwrite, proactive)
    return jsonify({"job_id": job_id}), 202

@app.route("/api/scan", methods=["POST"])
def api_scan():
    body = request.get_json(force=True, silent=True) or {}
    video_path = body.get("video_path", "")
    raw_threshold = float(body.get("threshold", 8))
    
    # Map legacy Hamming threshold (1-32) to AI Cosine threshold (1.0 - 0.0)
    if raw_threshold > 1.0:
        if raw_threshold <= 8:
            threshold = 0.98 - (raw_threshold - 1) * (0.13 / 7) # 1->0.98, 8->0.85
        else:
            threshold = 0.85 - (raw_threshold - 8) * (0.35 / 24) # 8->0.85, 32->0.50
    else:
        threshold = raw_threshold
        
    print(f"DEBUG: Scan Threshold mapped from {raw_threshold} to AI Cosine {threshold:.4f}")
    
    interval = float(body.get("interval", FRAME_INTERVAL_SEC))
    run_yolo = bool(body.get("run_yolo", True))
    target_clip = body.get("target_clip", None)
    speed_inv = bool(body.get("speed_invariant", True))
    temporal_chk = bool(body.get("temporal_check", True))
    overlay_tol = bool(body.get("overlay_tolerance", True))
    if not video_path: return jsonify({"error": "video_path is required"}), 400
    job_id, _ = _new_job("scan")
    get_queue().enqueue(job_id, _worker_scan, video_path, threshold, interval, run_yolo, target_clip, speed_inv, temporal_chk, overlay_tol)
    return jsonify({"job_id": job_id}), 202

@app.route("/api/auto_ingest", methods=["POST"])
def api_auto_ingest():
    body = request.get_json(force=True, silent=True) or {}
    topic = body.get("topic", "")
    auto_scan = bool(body.get("auto_scan", True))
    if not topic: return jsonify({"error": "topic is required"}), 400
    job_id, _ = _new_job("auto_ingest")
    get_queue().enqueue(job_id, _worker_auto_ingest, topic, auto_scan)
    return jsonify({"job_id": job_id}), 202

@app.route("/api/stream/<job_id>")
def api_stream(job_id: str):
    job = storage.get_job(job_id)
    if not job: abort(404)
    def generate():
        q = get_queue().get_bus(job_id)
        if job["status"] in ("done", "error"):
             yield _sse({"type": job["status"], "result": job.get("result"), "message": "Job already completed."})
             return
        yield _sse({"type": "connected", "job_id": job_id})
        while True:
            try:
                event = q.get(timeout=0.4)
                yield _sse(event)
                if event.get("type") in ("done", "error"): break
            except Empty:
                job_check = storage.get_job(job_id)
                if job_check["status"] in ("done", "error"): break
                yield ": heartbeat\n\n"
    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/reports", methods=["GET", "DELETE"])
def api_reports():
    if request.method == "DELETE":
        storage.clear_all_reports()
        return jsonify({"message": "All reports cleared"}), 200
        
    return jsonify([{
        "filename": r.get("report_filename", "unnamed.json"),
        "suspect": r.get("suspect_video", "unknown"),
        "similarity": r.get("similarity_percentage", 0),
        "verdict": r.get("verdict", ""),
        "generated": r.get("generated_at", ""),
        "frames": r.get("total_frames_checked", 0),
        "matched": r.get("matched_frames", 0),
        "pdf_available": r.get("dmca_pdf_available", False)
    } for r in storage.list_reports(100)])

@app.route("/api/reports/<filename>/dmca")
def api_report_dmca_pdf(filename: str):
    from flask import send_file
    safe_name = filename.replace(".json", "") + "_DMCA.pdf"
    pdf_path = BASE_DIR / "reports" / "dmca_notices" / safe_name
    if not pdf_path.exists():
        abort(404, description="DMCA PDF not available for this report (requires detected matches)")
    return send_file(str(pdf_path), as_attachment=True, download_name=safe_name)

@app.route("/api/reports/<filename>/analyze", methods=["POST"])
def api_report_analyze(filename: str):
    try:
        report = storage.get_report(filename)
        if not report: abort(404)
        analysis = ai_engine.analyze_report(report)
        return jsonify({"analysis": analysis, "model": ai_engine.mode})
    except Exception as e:
        print(f"ERROR: Analysis failed for {filename}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/reports/<filename>")
def api_report_detail(filename: str):
    report = storage.get_report(filename)
    if not report: abort(404)
    return jsonify(report)

@app.route("/api/db", methods=["GET", "DELETE"])
def api_db():
    from core.storage import get_storage
    storage = get_storage()
    if request.method == "DELETE":
        try:
            from core.qdrant_store import QdrantStore, COLLECTION_NAME
            qdrant = QdrantStore()
            # Clear Qdrant
            qdrant.client.delete_collection(COLLECTION_NAME)
            qdrant._ensure_collection()
            # Clear Mongo
            storage.clear_hashes()
            return jsonify({"message": "Database wiped successfully"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    # GET: List clips
    clips = list(storage.clips.find({}, {"_id": 0}))
    return jsonify({"clips": clips})

@app.route("/api/jobs")
def api_jobs():
    return jsonify(storage.list_jobs(50))

@app.route("/api/discovery/results")
def api_discovery_results():
    return jsonify(storage.list_discovery_results(100))

@app.route("/api/human_feedback", methods=["POST"])
def api_human_feedback():
    """Adds manual confirm/reject feedback loops for model threshold tuning."""
    body = request.get_json(force=True, silent=True) or {}
    report_id = body.get("report_filename")
    verdict_auth = bool(body.get("is_authorized", False))
    if not report_id: return jsonify({"error": "report missing"}), 400
    storage.update_report_feedback(report_id, verdict_auth)
    return jsonify({"message": "Feedback recorded. Rules dynamically updated."})

@app.route("/api/ai_status")
def api_ai_status():
    status = "ready" if "Gemini" in ai_engine.mode else "offline"
    if hasattr(ai_engine.provider, 'model') and ai_engine.provider.model is None:
        status = "offline"
    
    # Bundle jobs to save a round-trip
    jobs = storage.list_jobs(12)
    active = sum(1 for j in jobs if j["status"] == "running")
    
    return jsonify({
        "gemini": status,
        "yolo": "ready" if YOLO_AVAILABLE else "offline",
        "mode": ai_engine.mode,
        "active_jobs": active,
        "recent_jobs": jobs
    })

@app.route("/api/stats")
def api_stats():
    """Aggregates all dashboard metrics into one call."""
    from core.qdrant_store import QdrantStore
    q_store = QdrantStore()
    return jsonify({
        "clips": storage.clips.count_documents({}),
        "frames": q_store.count_frames(),
        "reports": storage.reports.count_documents({}),
        "jobs": sum(1 for j in storage.list_jobs(50) if j["status"] == "running")
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000, debug=True, threaded=True)
