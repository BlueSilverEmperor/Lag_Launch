# TECHNICAL BLUEPRINT: WRAITH ASSET PROTECTION SYSTEM

**Date:** April 27, 2026  
**Subject:** Full Stack Production Audit & Rebuild Specification  
**System Version:** v3.5m (Cloud-Native)

---

## 1. 🧾 Executive Overview

### Project Purpose
WRAITH is an advanced, AI-driven Digital Asset Protection (DAP) system designed for sports leagues, film studios, and high-value content owners. It proactively monitors the public internet for unauthorized rebroadcasts, performs frame-level visual verification, and automates rights enforcement.

### Core Problem Solved
The "Piracy Filter" problem. Traditional piracy detection (e.g., YouTube's standard ContentID) is easily bypassed by simple filters like cropping, mirroring, color shifting, or overlays. WRAITH uses **Perceptual Neural Hashing** to "see" the content semantically, making it immune to these common pirate tactics.

### Key Differentiators
- **Multimodal Verification**: Unlike systems that rely on one method, WRAITH uses a 3-layer verification stack (CLIP Vectors -> YOLO Logo Detection -> Gemini Reasoning).
- **0-Day Resilience**: Capable of ingesting and fingerprinting live broadcast feeds in real-time.
- **Auto-Enforcement**: Generates legally compliant DMCA notices and evidence heatmaps automatically.

---

## 2. 🧱 System Architecture (Deep Dive)

### High-Level Architecture
WRAITH is architected as a **Concurrency-First Monolith** with containerized service dependencies.

```text
[ USER UI ] <──(HTTP/SSE)──> [ FLASK SERVER ] <──(IPC)──> [ WORKER POOL ]
                                   │                          │
                                   ├─> [ QDRANT ] (Vectors)   ├─> [ CLIP ENGINE ]
                                   ├─> [ MONGODB ] (Metadata) ├─> [ YOLO DETECTOR ]
                                   └─> [ .ENV CFG ]          └─> [ GEMINI CLOUD ]
```

### Request Lifecycle (The "Scan" Journey)
1. **Ingestion**: User provides a URL. Flask validates and spawns an asynchronous `_worker_scan`.
2. **Phase 1 (Abstracting)**: The worker uses CLIP to generate perceptual vectors for every N-second interval.
3. **Phase 2 (Searching)**: Vectors are queried against the local **Qdrant** database using Cosine Similarity.
4. **Phase 3 (Confirming)**: If matches > Threshold, **YOLOv8** is triggered on the top 5 match-frames to detect official logos.
5. **Phase 4 (Reporting)**: Results are synthesized by **Gemini 1.5 Flash**. A DMCA PDF is generated.
6. **Delivery**: The frontend receives real-time updates via **Server-Sent Events (SSE)**.

---

## 3. 🧰 Tech Stack (With Justification)

| Layer | Technology | Justification |
| :--- | :--- | :--- |
| **Frontend** | Vanilla JS / CSS | Zero-dependency build footprint; maximum runtime performance for long-lived dashboards. |
| **Backend** | Python / Flask | Fast prototyping of ML pipelines and robust threading support for I/O bound tasks. |
| **Vector DB** | Qdrant | Optimized for high-speed nearest-neighbor search; local persistence support. |
| **Metadata DB** | MongoDB | Highly flexible schema for varying job results and metadata from discovery crawlers. |
| **Vision Model**| OpenAI CLIP | State-of-the-art zero-shot visual similarity; resilient to crops and compression. |
| **Object Det.** | YOLOv8 (v8n) | Fastest detection engine for broadcast logo recognition. |
| **LLM Engine** | Gemini 1.5 Flash | massive context window for scan-log analysis with best-in-class cost-to-speed ratio. |
| **Deployment** | Docker | Ensures parity between Local-Host fallback and Cloud-DAP modes. |

---

## 4. 🗄️ Data Architecture

### Database Schemas

#### MongoDB: `dap_db`
- **`clips`**: Stores original ingested asset metadata (name, frame count, qdrant-hash-id).
- **`jobs`**: Real-time status tracker (running, done, error) for ingestion/scans.
- **`reports`**: Persistence for all generated scan results, verdicts, and DMCA file paths.
- **`discovery`**: High-risk URLs found by the proactive hunting engine.

#### Qdrant: `video_frames`
- **Vector**: 512-dimension float array (CLIP Embeddings).
- **Payload**: `{"clip_name": str, "timestamp": float}`.
- **Index**: HNSW (Hierarchical Navigable Small World) for sub-millisecond search at scale.

---

## 5. 🔄 Workflows & Business Logic

### The "Global Discovery" Pipeline
1. **Topic Trigger**: User enters "Premier League".
2. **Query Expansion**: Gemini expands this to slang variants (e.g., "PL Live Stream free").
3. **Multi-Source Crawling**: Parallel requests to Google, Bing, and Social APIs.
4. **Risk Scoring**: Each result is ranked (High/Mid/Low) based on domain reputation and uploader subscriber count (yt-dlp metadata).
5. **Auto-Scan Queue**: High-risk links are optionally auto-queued for visual scanning.

---

## 6. 🔌 API Design

### Core API Endpoints
- `POST /api/scan`: Initiates a new asset scan.
- `GET /api/stream/<job_id>`: SSE stream for real-time progress updates.
- `GET /api/stats`: Consolidated dashboard metrics (Clips, Frames, Jobs).
- `GET /api/ai_status`: Real-time health check for Gemini/YOLO layers.
- `POST /api/reports/<filename>/analyze`: Triggers Gemini narrative generation.

---

## 🔐 10. Security Architecture

WRAITH employs a multi-layered **Hardened Perimeter** strategy to protect rights data and prevent unauthorized tampering.

### A. The Application Firewall (`core/security.py`)
- **Anti-Debugging Logic**: The `SecurityGatekeeper` checks for debugger attachments. If detected in a production run, it immediately terminates the process to prevent reverse-engineering of the vector extraction logic.
- **Environment Gating**: A strict `.env` validation layer ensures that no data leaks occur to public APIs (like Gemini) unless explicitly configured via the `RUN_MODE=DOCKER` flag.
- **Filename Sanitization**: As seen in `server_reloaded.py`, a regex-based sanitization layer (`sanitize_filename`) prevents directory traversal attacks and OS-level crash attempts using illegal filesystem characters.

### B. Data & Identity Protection
- **Vector Anonymization**: Qdrant stores vectors (mathematical points), not the raw pixels of the official clips. Even if the DB is breached, the original video cannot be reconstructed from the vectors.
- **Rate-Limit Guard**: The backend limits the frequency of incoming API stats requests to prevent resource exhaustion (Denial of Service).

---

## 🚀 11. DevOps & Rebuild Guide

### 🛠️ Rebuild Instructions (Step-by-Step)

#### Step 1: Environment Setup
1. Install **Python 3.10+**.
2. Install **Docker Desktop**.
3. (Optional) Setup **CUDA 11.8** for GPU acceleration on YOLO/CLIP.

#### Step 2: Dependency Initialization
```powershell
pip install -r requirements.txt
```

#### Step 3: Local Configuration
Create a `.env` file in the root:
```env
GOOGLE_API_KEY=your_key_here
RUN_MODE=DOCKER
QDRANT_HOST=localhost
MONGO_URI=mongodb://localhost:27017
```

#### Step 4: Container Orchestration
```bash
docker-compose up -d --build
```
This launches the Qdrant and MongoDB clusters required for persistence.

---

## 🧠 16. AI/Prompt Engineering Layer

The intelligence layer is driven by **Structured Prompting**, moving beyond simple chat interactions to "Expert reasoning" output.

### A. Professional Persona Engineering
All Gemini interactions are primed with a "Digital Rights Enforcement Expert" persona. This ensures the output is legally formal, precise, and devoid of AI hallucinations.

### B. The "Executive Summary" Prompt Pattern
We utilize a **Triple-Objective Prompt** in the `GeminiProvider`:
1. **Evidence Verification**: Forces the AI to cite specific match percentages from the scan data.
2. **Logo Confirmation**: Cross-references the YOLOv8 detections with the similarity score.
3. **Legal Path**: Requests a concrete recommendation (Immediate takedown vs. Manual review).

### C. Heuristic Fallback
If the Prompt Layer returns an error or rate-limit message, the system uses a **Pattern-Matching Heuristic** (`LocalFallbackProvider`) to provide a basic risk verdict, ensuring WRAITH is never "blind."

---

## ⚠️ Risks & Future Improvements

### Technical Risks
- **Socket Exhaustion (Windows)**: High-frequency UI polling (every 1s) can crash the Flask server. **Fixed** in v3.5m via stats consolidation.
- **API Rate Limits**: Dependence on Gemini/Google Search for "Global Reach." **Mitigation**: Implemented `LocalFallbackProvider`.

### Future Roadmap
- **Blockchain Timestamps**: Storing report hashes on-chain for immutable legal evidence.
- **Live Stream Interception**: Direct RTMP/HLS ingestion for 0-second latency detection.
- **Collaborative Enforcement**: Sharing high-risk uploader databases across a network of WRAITH instances.
