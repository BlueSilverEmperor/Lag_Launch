"""
core/storage.py
---------------
MongoDB Storage Layer for Digital Asset Protection.
Handles persistence of hashes, jobs, and reports.
"""

import json
import uuid
import datetime
from typing import Any, Dict, List, Optional
from pymongo import MongoClient, DESCENDING, UpdateOne

class MongoStorage:
    def __init__(self, uri=None, database="dap_db"):
        import os
        import time
        from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
        
        actual_uri = uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        
        # Implement retry logic for Docker startup resiliency
        max_retries = 5
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                self.client = MongoClient(actual_uri, serverSelectionTimeoutMS=5000)
                # Force a connection check
                self.client.admin.command('ping')
                print(f"DEBUG: MongoDB connected successfully on attempt {attempt + 1}")
                break
            except (ConnectionFailure, ServerSelectionTimeoutError) as e:
                if attempt == max_retries - 1:
                    print(f"ERROR: Could not connect to MongoDB after {max_retries} attempts.")
                    raise e
                print(f"DEBUG: MongoDB not ready (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2

        self.db = self.client[database]

        
        # Collections
        self.clips = self.db["clips"]
        self.jobs = self.db["jobs"]
        self.reports = self.db["reports"]
        self.authorized_publishers = self.db["authorized_publishers"]
        self.discovery = self.db["discovery_results"]
        self.monitored_urls = self.db["monitored_urls"]
        
        # Ensure Indexes
        self._ensure_indexes()

    def _ensure_indexes(self):
        """Create necessary indexes for performance."""
        self.clips.create_index("name", unique=True)
        self.jobs.create_index("id", unique=True)
        self.jobs.create_index([("created_at", DESCENDING)])
        self.reports.create_index("report_filename", unique=True)
        self.reports.create_index([("generated_at", DESCENDING)])
        self.authorized_publishers.create_index([("name", 1), ("platform", 1)], unique=True)
        self.discovery.create_index([("found_at", DESCENDING)])
        self.discovery.create_index("url", unique=True)
        self.monitored_urls.create_index("url", unique=True)

    # --- Hashes (Fingerprints) ---
    def save_hashes(self, clip_name: str, frame_hashes: Dict[str, str]):
        """Save or update hashes for a clip."""
        # Map frame_hashes to a list of dicts for Mongo storage
        # However, to maintain the same format for detection logic,
        # we can just store the dict directly as a sub-document.
        # Note: Mongo keys can't contain dots, but our timestamps are float strings.
        # We replace dots with underscores if necessary, or just store as a list of points.
        
        # Actually, pHash detection logic expects a Dict[str, str] where key is timestamp.
        # We'll store it in a way that doesn't break Mongo but is easy to retrieve.
        sanitized_hashes = {str(k).replace(".", "_"): v for k, v in frame_hashes.items()}
        
        self.clips.update_one(
            {"name": clip_name},
            {"$set": {
                "name": clip_name,
                "hashes": sanitized_hashes,
                "updated_at": datetime.datetime.now()
            }},
            upsert=True
        )

    def load_all_hashes(self) -> Dict[str, Dict[str, str]]:
        """Load all clip hashes into a nested dictionary."""
        result = {}
        for clip in self.clips.find():
            name = clip["name"]
            hashes = clip.get("hashes", {})
            # De-sanitize keys (restore dots)
            restored_hashes = {str(k).replace("_", "."): v for k, v in hashes.items()}
            result[name] = restored_hashes
        return result

    def clear_hashes(self):
        """Delete all hashes and clips."""
        self.clips.delete_many({})

    def get_hash_count(self) -> int:
        return self.clips.count_documents({})

    # --- Jobs ---
    def create_job(self, job_data: Dict[str, Any]):
        """Create a new job record."""
        # Ensure created_at is a datetime object
        data = job_data.copy()
        if isinstance(data.get("created_at"), str):
            try:
                data["created_at"] = datetime.datetime.fromisoformat(data["created_at"])
            except ValueError:
                data["created_at"] = datetime.datetime.now()
        else:
            data["created_at"] = datetime.datetime.now()
            
        self.jobs.insert_one(data)

    def update_job(self, job_id: str, updates: Dict[str, Any]):
        """Update an existing job."""
        self.jobs.update_one({"id": job_id}, {"$set": updates})

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.jobs.find_one({"id": job_id}, {"_id": 0})
        if job and isinstance(job.get("created_at"), datetime.datetime):
            job["created_at"] = job["created_at"].isoformat()
        return job

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        jobs = list(self.jobs.find({}, {"_id": 0}).sort("created_at", DESCENDING).limit(limit))
        for j in jobs:
            if isinstance(j.get("created_at"), datetime.datetime):
                j["created_at"] = j["created_at"].isoformat()
        return jobs

    def prune_jobs(self, keep_count: int = 50):
        """Remove oldest jobs if above limit."""
        count = self.jobs.count_documents({})
        if count > keep_count:
            # Find the timestamp of the N-th newest job
            oldest_to_keep = list(self.jobs.find().sort("created_at", DESCENDING).skip(keep_count - 1).limit(1))
            if oldest_to_keep:
                cutoff = oldest_to_keep[0]["created_at"]
                self.jobs.delete_many({"created_at": {"$lt": cutoff}})

    def get_running_job_count(self) -> int:
        return self.jobs.count_documents({"status": "running"})

    # --- Reports ---
    def save_report(self, report_data: Dict[str, Any]):
        """Save a scan report."""
        data = report_data.copy()
        if isinstance(data.get("generated_at"), str):
            try:
                data["generated_at"] = datetime.datetime.fromisoformat(data["generated_at"])
            except ValueError:
                data["generated_at"] = datetime.datetime.now()
        else:
            data["generated_at"] = datetime.datetime.now()
            
        self.reports.update_one(
            {"report_filename": data["report_filename"]},
            {"$set": data},
            upsert=True
        )

    def list_reports(self, limit: int = 100) -> List[Dict[str, Any]]:
        reports = list(self.reports.find({}, {
            "_id": 0,
            "report_filename": 1,
            "suspect_video": 1,
            "total_frames_checked": 1,
            "matched_frames": 1,
            "similarity_percentage": 1,
            "verdict": 1,
            "generated_at": 1,
            "compliance_status": 1,
            "compliance_reason": 1,
            "publisher": 1,
            "topics": 1,
            "frames": 1
        }).sort("generated_at", DESCENDING).limit(limit))
        
        for r in reports:
            if isinstance(r.get("generated_at"), datetime.datetime):
                r["generated_at"] = r["generated_at"].isoformat()
        return reports

    def get_report(self, filename: str) -> Optional[Dict[str, Any]]:
        report = self.reports.find_one({"report_filename": filename}, {"_id": 0})
        if report and isinstance(report.get("generated_at"), datetime.datetime):
            report["generated_at"] = report["generated_at"].isoformat()
        return report

    def get_report_count(self) -> int:
        return self.reports.count_documents({})

    def clear_all_reports(self):
        """Delete all generated scan reports."""
        self.reports.delete_many({})

    def update_report_feedback(self, filename: str, verdict_auth: bool):
        """Human-in-the-loop feedback to override false positives."""
        self.reports.update_one(
            {"report_filename": filename},
            {"$set": {
                "human_feedback": "AUTHORIZED" if verdict_auth else "CONFIRMED_PIRACY",
                "feedback_at": datetime.datetime.now()
            }}
        )

    # --- Authorized Publishers ---
    def add_authorized_publisher(self, name: str, platform: str, channel_url: str = ""):
        # Find next numeric ID for compatibility with legacy UI
        last = self.authorized_publishers.find_one(sort=[("id", -1)])
        next_id = (last["id"] + 1) if last and "id" in last else 1
        
        self.authorized_publishers.update_one(
            {"name": name, "platform": platform},
            {"$set": {"name": name, "platform": platform,
                      "channel_url": channel_url,
                      "added_at": datetime.datetime.now()},
             "$setOnInsert": {"id": next_id}},
            upsert=True
        )

    def remove_authorized_publisher(self, pub_id: int):
        self.authorized_publishers.delete_one({"id": int(pub_id)})

    def list_authorized_publishers(self) -> List[Dict[str, Any]]:
        pubs = list(self.authorized_publishers.find({}, {"_id": 0}))
        for p in pubs:
            if "added_at" in p and isinstance(p["added_at"], datetime.datetime):
                p["added_at"] = p["added_at"].isoformat()
        return pubs

    # --- 0-Day Monitored URLs ---
    def add_monitored_url(self, url: str):
        """Mark a URL as already hashed to avoid re-processing."""
        self.monitored_urls.update_one(
            {"url": url},
            {"$set": {"url": url, "added_at": datetime.datetime.now()}},
            upsert=True
        )

    def list_monitored_urls(self) -> List[str]:
        return [doc["url"] for doc in self.monitored_urls.find({}, {"url": 1, "_id": 0})]

    # --- Discovery Results ---
    def save_discovery_result(self, item: Dict[str, Any]):
        """Save a discovered piracy link."""
        data = item.copy()
        data["found_at"] = datetime.datetime.now()
        self.discovery.update_one(
            {"url": data["url"]},
            {"$set": data},
            upsert=True
        )

    def list_discovery_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        results = list(self.discovery.find({}, {"_id": 0}).sort("found_at", DESCENDING).limit(limit))
        for r in results:
            if "found_at" in r and isinstance(r["found_at"], datetime.datetime):
                r["found_at"] = r["found_at"].isoformat()
        return results

storage = None

def get_storage() -> MongoStorage:
    global storage
    if storage is None:
        storage = MongoStorage()
    return storage
