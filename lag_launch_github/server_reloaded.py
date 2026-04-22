from __future__ import annotations
print("DEBUG: Loading server.py from:", __file__)

import json
import uuid
import time
import threading
import traceback
import datetime as dt
from pathlib import Path
from queue import Queue, Empty

from flask import Flask, jsonify, request, Response, send_from_directory, abort
from flask_cors import CORS

# ─── Core + Pipeline imports ──────────────────────────────────────────────────
from core.hasher import hash_video, extract_frames, FRAME_INTERVAL_SEC
from core.detector import scan_suspect_video, load_hash_db, MATCH_THRESHOLD
from core.verifier import YOLO_AVAILABLE
from core.discovery import discover_videos
# ─── Constants & Utilities ──────────────────────────────────────────────────
VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"
}

BASE_DIR   = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_DB_PATH = BASE_DIR / "data" / "hash_db.json"
REPORTS_DIR = BASE_DIR / "reports"

def _load_db(db_path: Path) -> dict:
    if db_path.exists():
        with open(db_path, "r") as f:
            return json.load(f)
    return {}

def _save_db(db: dict, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with open(db_path, "w") as f:
        json.dump(db, f, indent=2)

# ─── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
CORS(app)

# ─── Job registry ─────────────────────────────────────────────────────────────
# Structure: { job_id: { status, type, queue, result, error, created_at } }
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS  = 50   # keep last N jobs in memory


def _new_job(job_type: str) -> tuple[str, dict]:
    job_id = str(uuid.uuid4())
    job = {
        "id":         job_id,
        "type":       job_type,
        "status":     "running",
        "queue":      Queue(),
        "result":     None,
        "error":      None,
        "created_at": dt.datetime.now().isoformat(),
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
        # Prune oldest jobs if over limit
        if len(JOBS) > MAX_JOBS:
            oldest = sorted(JOBS.keys(), key=lambda k: JOBS[k]["created_at"])[0]
            JOBS.pop(oldest, None)
    return job_id, job


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

def _worker_ingest(job_id: str, source: str, interval_sec: float, overwrite: bool) -> None:
    job = JOBS[job_id]
    q: Queue = job["queue"]

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

        db = _load_db(DEFAULT_DB_PATH)
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
            _save_db(db, DEFAULT_DB_PATH)
            ingested += 1

            q.put({
                "type": "progress", "index": i + 1, "total": total,
                "clip": vid_name, "frames": len(frame_hashes),
                "elapsed": round(elapsed, 2), "skipped": False,
                "message": f"[{i+1}/{total}] Done: {vid_name} — {len(frame_hashes)} frames ({elapsed:.1f}s)",
            })

        result = {
            "total_clips": total,
            "ingested": ingested,
            "skipped": skipped,
            "db_clips": len(db),
        }
        job["status"] = "done"
        job["result"] = result
        q.put({"type": "done", "result": result,
               "message": f"Ingestion complete — {len(db)} clip(s) in DB"})

    except Exception as exc:
        err_msg = _strip_ansi(str(exc))
        job["status"] = "error"
        job["error"]  = err_msg
        q.put({"type": "error", "message": err_msg, "trace": traceback.format_exc()})


def _worker_scan(
    job_id: str,
    video_path: str,
    threshold: int,
    interval_sec: float,
    run_yolo: bool,
    target_clip: str = None,
) -> None:
    job = JOBS[job_id]
    q: Queue = job["queue"]

    try:
        downloader = ResilientDownloader(q)
        is_url = video_path.startswith("http://") or video_path.startswith("https://")
        if is_url:
            q.put({"type": "info", "message": f"Downloading suspect video from URL..."})
            path, vid_name = downloader.download(video_path)
            stream_url = str(path)
        else:
            vp = Path(video_path)
            if not vp.is_file():
                raise FileNotFoundError(f"Video file not found: {video_path}")
            stream_url = str(vp)
            vid_name = vp.name

        hash_db = load_hash_db(DEFAULT_DB_PATH)
        if not hash_db:
            raise RuntimeError("Hash DB is empty — run ingestion first.")

        if target_clip:
            if target_clip not in hash_db:
                raise ValueError(f"Target clip '{target_clip}' not found in database.")
            hash_db = {target_clip: hash_db[target_clip]}

        q.put({"type": "start",
               "message": f"Scanning '{vid_name}' against {len(hash_db)} clip(s)"})

        # ── Phase 2: Hash suspect ─────────────────────────────────────────
        q.put({"type": "phase", "phase": 2, 
               "message": f"Hashing frames (interval: {interval_sec}s)..."})
        
        suspect_hashes = hash_video(stream_url, interval_sec)
        if not suspect_hashes:
            q.put({"type": "warning", "message": f"Found 0 frames for {vid_name}"})
        else:
            q.put({
                "type": "hashed",
                "frames": len(suspect_hashes),
                "message": f"Hashed {len(suspect_hashes)} keyframes from suspect video",
            })

        # ── Phase 2: Compare ──────────────────────────────────────────────
        q.put({"type": "phase", "phase": 2,
               "message": "Comparing frames against database (Hamming distance)..."})

        report = scan_suspect_video(suspect_hashes, vid_name, hash_db, threshold)

        q.put({
            "type": "detection_done",
            "matched": report.matched_frames,
            "total":   report.total_frames_checked,
            "similarity": report.similarity_percentage,
            "verdict": report.verdict,
            "message": (
                f"Detection complete — {report.matched_frames}/{report.total_frames_checked} "
                f"frames matched ({report.similarity_percentage}%)"
            ),
        })

        # ── Phase 3: YOLO ─────────────────────────────────────────────────
        yolo_results = []

        if run_yolo and report.matched_frames > 0:
            if not YOLO_AVAILABLE:
                q.put({"type": "warning",
                       "message": "YOLOv8 not installed — skipping logo verification"})
            else:
                q.put({"type": "phase", "phase": 3,
                       "message": f"Phase 3 — Running YOLOv8 on {report.matched_frames} matched frame(s)..."})

                from core.verifier import LogoVerifier
                verifier = LogoVerifier()
                matched_ts = {r.suspect_timestamp for r in report.frame_results if r.is_match}

                for ts, frame in extract_frames(stream_url, interval_sec):
                    rounded = round(ts, 2)
                    if rounded in matched_ts or ts in matched_ts:
                        det = verifier.verify_frame(ts, frame)
                        yolo_results.append(det)
                        q.put({
                            "type": "yolo_frame",
                            "timestamp": ts,
                            "logo": det.logo_detected,
                            "confidence": round(det.confidence, 3),
                            "classes": det.detected_classes,
                            "message": (
                                f"YOLO @ {ts:.1f}s — "
                                f"{'🚨 Logo detected' if det.logo_detected else '✓ No logo'} "
                                f"({det.confidence:.0%})"
                            ),
                        })

        # ── Phase 4: Build report ─────────────────────────────────────────
        q.put({"type": "phase", "phase": 4, "message": "Phase 4 — Generating report..."})

        yolo_map = {d.timestamp: d for d in yolo_results}

        def _flag(is_match: bool, logo: bool) -> str:
            if is_match and logo:   return "CONFIRMED INFRINGEMENT"
            elif is_match:          return "SUSPECTED COPY"
            else:                   return "CLEAR"

        def _ts_fmt(s) -> str:
            if s is None: return "—"
            m, sec = divmod(int(s), 60)
            return f"{m:02d}:{sec:02d}"

        frames_out = []
        for fr in report.frame_results:
            yolo = yolo_map.get(fr.suspect_timestamp)
            logo_det = yolo.logo_detected if yolo else False
            frames_out.append({
                "suspect_timestamp":  fr.suspect_timestamp,
                "suspect_time_fmt":   _ts_fmt(fr.suspect_timestamp),
                "hamming_distance":   fr.best_distance,
                "is_match":           fr.is_match,
                "matched_clip":       fr.matched_clip,
                "matched_timestamp":  fr.matched_timestamp,
                "logo_detected":      logo_det,
                "logo_confidence":    round(yolo.confidence, 3) if yolo else None,
                "flag_status":        _flag(fr.is_match, logo_det),
            })

        logo_confirmations = sum(1 for d in yolo_results if d.logo_detected)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts_str = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Use sanitized vid_name for filename
        safe_stem = "".join([c if c.isalnum() or c in "._-" else "_" for c in vid_name])
        report_filename = f"{safe_stem}_{ts_str}_report.json"
        report_path = REPORTS_DIR / report_filename

        json_data = {
            "generated_at":          dt.datetime.now().isoformat(),
            "suspect_video":         vid_name,
            "total_frames_checked":  report.total_frames_checked,
            "matched_frames":        report.matched_frames,
            "similarity_percentage": report.similarity_percentage,
            "logo_confirmations":    logo_confirmations,
            "verdict":               report.verdict,
            "frames":                frames_out,
        }

        with open(report_path, "w") as f:
            json.dump(json_data, f, indent=2)

        job["status"] = "done"
        job["result"] = json_data
        q.put({
            "type": "done",
            "result": json_data,
            "report_file": report_filename,
            "message": f"Report saved → {report_filename}",
        })

    except Exception as exc:
        err_msg = _strip_ansi(str(exc))
        job["status"] = "error"
        job["error"]  = err_msg
        q.put({"type": "error", "message": err_msg, "trace": traceback.format_exc()})


def _worker_auto_ingest(job_id: str, topic: str, auto_scan: bool) -> None:
    job = JOBS[job_id]
    q: Queue = job["queue"]
    
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

        job["status"] = "done"
        job["result"] = results
        q.put({
            "type": "done",
            "result": results,
            "message": "Auto Ingestion complete!"
        })

    except Exception as exc:
        err_msg = _strip_ansi(str(exc))
        job["status"] = "error"
        job["error"]  = err_msg
        q.put({"type": "error", "message": err_msg, "trace": traceback.format_exc()})


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/status")
def api_status():
    db = _load_db(DEFAULT_DB_PATH)
    total_frames = sum(len(v) for v in db.values())
    reports = list(REPORTS_DIR.glob("*.json")) if REPORTS_DIR.exists() else []

    with JOBS_LOCK:
        running = sum(1 for j in JOBS.values() if j["status"] == "running")

    return jsonify({
        "db_clips":     len(db),
        "total_frames": total_frames,
        "report_count": len(reports),
        "running_jobs": running,
        "yolo_available": YOLO_AVAILABLE,
        "db_path":      str(DEFAULT_DB_PATH),
    })


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    body        = request.get_json(force=True, silent=True) or {}
    source      = body.get("source", body.get("clips_dir", ""))
    interval    = float(body.get("interval", FRAME_INTERVAL_SEC))
    overwrite   = bool(body.get("overwrite", False))

    if not source:
        return jsonify({"error": "source is required"}), 400

    job_id, _ = _new_job("ingest")
    t = threading.Thread(
        target=_worker_ingest,
        args=(job_id, source, interval, overwrite),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/scan", methods=["POST"])
def api_scan():
    body        = request.get_json(force=True, silent=True) or {}
    video_path  = body.get("video_path", "")
    threshold   = int(body.get("threshold", MATCH_THRESHOLD))
    interval    = float(body.get("interval", FRAME_INTERVAL_SEC))
    run_yolo    = bool(body.get("run_yolo", True))
    target_clip = body.get("target_clip", None)

    if not video_path:
        return jsonify({"error": "video_path is required"}), 400

    job_id, _ = _new_job("scan")
    t = threading.Thread(
        target=_worker_scan,
        args=(job_id, video_path, threshold, interval, run_yolo, target_clip),
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
    job = JOBS.get(job_id)
    if not job:
        abort(404)

    def generate():
        q: Queue = job["queue"]
        # Send initial heartbeat
        yield _sse({"type": "connected", "job_id": job_id})

        while True:
            try:
                event = q.get(timeout=0.4)
                yield _sse(event)
                if event.get("type") in ("done", "error"):
                    break
            except Empty:
                if job["status"] in ("done", "error"):
                    break
                yield ": heartbeat\n\n"   # SSE comment keeps connection alive

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
    with JOBS_LOCK:
        jobs_out = [
            {
                "id":         j["id"],
                "type":       j["type"],
                "status":     j["status"],
                "created_at": j["created_at"],
                "error":      j.get("error"),
            }
            for j in sorted(JOBS.values(), key=lambda x: x["created_at"], reverse=True)
        ]
    return jsonify(jobs_out)


@app.route("/api/reports")
def api_reports():
    if not REPORTS_DIR.exists():
        return jsonify([])
    reports = []
    for p in sorted(REPORTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(p) as f:
                data = json.load(f)
            reports.append({
                "filename":   p.name,
                "suspect":    data.get("suspect_video", p.stem),
                "similarity": data.get("similarity_percentage", 0),
                "verdict":    data.get("verdict", ""),
                "generated":  data.get("generated_at", ""),
                "frames":     data.get("total_frames_checked", 0),
                "matched":    data.get("matched_frames", 0),
            })
        except Exception:
            pass
    return jsonify(reports)


@app.route("/api/reports/<filename>")
def api_report_detail(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists() or not path.suffix == ".json":
        abort(404)
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/db", methods=["GET"])
def api_db_info():
    db = _load_db(DEFAULT_DB_PATH)
    clips = [
        {"name": name, "frames": len(hashes)}
        for name, hashes in db.items()
    ]
    return jsonify({"clips": clips, "total_clips": len(clips)})


@app.route("/api/db", methods=["DELETE"])
def api_db_clear():
    if DEFAULT_DB_PATH.exists():
        DEFAULT_DB_PATH.unlink()
    return jsonify({"message": "Hash database cleared."})


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║  DAP Server v2.0b • http://127.0.0.1:9000    ║")
    print("  ╚══════════════════════════════════════════════╝\n")
    app.run(host="0.0.0.0", port=9000, debug=False, threaded=True)
