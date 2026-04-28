# WRAITH — Digital Asset Protection (DAP) System

**WRAITH V3.5m Cloud-Native** is a premium, multimodal AI intelligence platform designed to proactively detect, verify, and dismantle unauthorized media distribution (piracy) across the global digital landscape. It provides zero-day resilience for sports leagues, film studios, and high-value content owners.

---

## 💥 The Core Problem Solved
Traditional piracy detection (like standard ContentID) is easily bypassed by simple filters (cropping, mirroring, color shifting, or overlays). WRAITH overcomes this using **Perceptual Neural Hashing** and advanced vision models to "see" content semantically, destroying conventional pirate evasion tactics.

---

## 🚀 Key Features & Pipelines

- **1. Autonomous Piracy Discovery Engine:** Uses **Sematic Reasoning AI (Gemini / DeepSeek-R1)** to synthesize multi-lingual search queries and orchestrates parallel crawls across 14+ global platforms (Reddit, Telegram, VK, TikTok, etc.) to discover high-risk URLs.
- **2. Zero-Day Hashing & Ingestion:** Persistent background watchers fingerprint original content. WRAITH uses black-box cropping to protect fingerprints against letterboxing or localized overlays, securing hashes immutably to a local MongoDB.
- **3. Multimodal Verification (Vision + Vectors):** 
  - **Phase 1:** Queries CLIP perceptual vectors against **Qdrant Index** to find exact clip matches regardless of speed manipulation (±15%).
  - **Phase 2:** Leverages **YOLOv8** object detection on high-confidence frames to perform secondary verification (detecting brand logos/watermarks).
- **4. AI Compliance & Action Center:** Generates detailed DMCA evidence heatmaps automatically and uses LLMs to synthesize executive summaries recommending legal takedown pathways.

---

## 🛠 Tech Stack

| Component | Technology | Justification |
| :--- | :--- | :--- |
| **Backend Framework** | Python 3.13, Flask (Async) | Supports real-time Server-Sent Events (SSE) and fast prototyping. |
| **Vector DB** | Qdrant (CLIP Embeddings) | Sub-millisecond similarity queries across millions of frames. |
| **Metadata DB** | MongoDB | Highly flexible schema for tracking asset jobs, discovery, and reports. |
| **AI (LLM)** | Google Gemini / DeepSeek-R1 | Evaluates uploader reputation and summarizes visual evidence logs. |
| **Visual Validation** | Ultralytics YOLOv8 / Llava | Specialized object detection for verifying original brand watermarks. |
| **Web UI** | Vanilla JS, CSS3 | Wraith Dark-Glassmorphism system; highly responsive without heavy frameworks. |

---

## 🔐 Advanced Security

WRAITH employs a multi-layered **Hardened Perimeter** strategy:
- **Application Gatekeeper:** Ships with active anti-debugging logic, shutting down execution if reverse-engineering tools or unauthorized VM attachment is detected.
- **Architectural Fallbacks:** Employs a `LocalFallbackProvider` heuristic. If Cloud AI endpoints hit a rate limit or network partition occurs, the internal system can still safely generate localized risk reports so the dashboard never goes blind.
- **Anonymized Vectors:** Only non-reversible math hashes (CLIP vectors) are stored. In the event of a breach, actual proprietary media frames cannot be reconstructed.

---

## 🏗 Installation & Local Setup

### 1. Environment Configuration
Create a `.env` file in the root directory:
```env
# Switch runtime mode
RUN_MODE=DOCKER 

# Core APIs
GOOGLE_API_KEY=your_gemini_api_key

# Databases
QDRANT_HOST=qdrant
MONGO_URI=mongodb://mongo:27017/dap_db
```

### 2. Cloud Deployment via Docker (Recommended)
This replicates the fully resilient cloud environment with the necessary database containers map.
```bash
docker-compose up -d --build
```
The glassmorphic dashboard will be listening at **http://localhost:9000**.

### 3. Native Python Setup
For local development and UI adjustments:
1. **Dependencies**: `pip install -r requirements.txt`
2. **Databases**: Ensure MongoDB and Qdrant are running locally beforehand.
3. **Run Bootstrapper**: `python main.py` (which verifies security before launching the server).

---

## 📂 Architecture Overview

```text
Asset Protection Cloud/
├── core/
│   ├── ai_engine.py      # Cloud/Local AI Abstraction Routing
│   ├── qdrant_store.py   # Vector HNSW Indexing
│   ├── storage.py        # MongoDB connection handling 
│   ├── security.py       # Sandbox & Firewall Gatekeeper
│   ├── verifier.py       # Multi-staged temporal alignment
│   └── detector.py       # pHash and Frame Extraction Engine
├── static/               # Client-side UI & Orbs animation
├── reports/              # Auto-generated PDF DMCA evidence
├── Dockerfile            # Production Image wrapper
├── docker-compose.yml    # Database Stack automation
├── server_reloaded.py    # Flask Worker & SSE Hub
└── main.py              # Application Entry / Startup Checks
```
