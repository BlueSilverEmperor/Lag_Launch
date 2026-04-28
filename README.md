# WRAITH — Cloud Edition

A production-grade, AI-driven **WRAITH** engine for detecting unauthorized media distribution. This version is **Cloud Ready** and optimized for deployment on Google Cloud Platform (GCP).

---

## 🚀 Cloud-Ready Features

- **Multi-Vector Search**: Powered by **Qdrant** for high-speed semantic frame matching.
- **Persistent Metadata**: Built on **MongoDB** for robust job and report tracking.
- **AI Abstraction Layer**: Native support for **Google Gemini** (Vertex AI) with local fallback.
- **Containerized**: One-click deployment via **Docker** and **Docker Compose**.
- **Real-time Monitoring**: Glassmorphic web dashboard with Server-Sent Events (SSE).

---

## 🛠 Tech Stack

| Component | Technology |
| :--- | :--- |
| **Backend** | Python 3.13, Flask (Async) |
| **Vector DB** | Qdrant (CLIP Embeddings) |
| **Metadata DB** | MongoDB |
| **AI (LLM/Vision)** | Google Gemini / DeepSeek-R1 |
| **Visual Verification** | Ultralytics YOLOv8 |
| **Web UI** | Vanilla JS, CSS3 (Glassmorphism) |

---

## 🏗 Installation & Local Setup

### Using Docker (Recommended)
This replicates the cloud environment locally.

```bash
docker-compose up --build
```
The dashboard will be available at `http://localhost:9000`.

### Native Setup
1. **Dependencies**: `pip install -r requirements.txt`
2. **Databases**: Ensure MongoDB and Qdrant are running locally.
3. **Run**: `python server_reloaded.py`

---

## ☁️ Google Cloud Integration

This system is designed to satisfy requirements for **Google AI** and **Cloud Deployment**.

### 1. Requirements Checklist
- [x] **Cloud Deployment**: Supported via `Dockerfile` and Cloud Run configuration.
- [x] **Google AI Service**: Integrated via `core/ai_engine.py` (Gemini Provider).

### 2. Enabling Gemini
Set the following environment variable to switch from Local Fallback to Google AI:
```bash
export GOOGLE_API_KEY="your_api_key_here"
```

---

## 📂 Architecture

```
Asset Protection/
├── core/
│   ├── ai_engine.py   # Google Gemini / Local AI Abstraction [NEW]
│   ├── qdrant_store.py# Vector Search logic
│   ├── storage.py     # MongoDB persistence
│   └── detector.py    # Fingerprinting engine
├── Dockerfile         # Cloud Platform build file [NEW]
├── docker-compose.yml # Orchestration [NEW]
├── server_reloaded.py # Flask API + SSE Workers
└── static/            # Glassmorphic Web Dashboard
```
