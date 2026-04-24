def _worker_scan(
    job_id: str,
    video_path: str,
    threshold: int,
    interval_sec: float,
    run_yolo: bool,
    target_clip: str = None,
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
            import cv2  # Force import in thread scope just in case
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
                report = scan_suspect_video({}, vid_name, hash_db, threshold)
            else:
                q.put({"type": "hashed", "frames": len(suspect_hashes), "message": f"Hashed {len(suspect_hashes)} frames."})
                report = scan_suspect_video(suspect_hashes, vid_name, hash_db, threshold)
                
            compliance_event.wait(timeout=60) # Increased timeout for LLM

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
            "report_url": f"/api/reports/{report_filename}",
            "message": f"Scan complete. Verdict: {report.verdict}"
        })

    except Exception as e:
        q.put({"type": "error", "message": f"Pipeline Error: {str(e)}"})
        traceback.print_exc()
