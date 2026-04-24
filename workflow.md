# Digital Asset Protection (DAP) System

The DAP System is a highly sophisticated, multimodal AI engine designed to proactively detect, verify, and document unauthorized media distribution (piracy) across the internet.

---

## 🛠 Tech Stack

### Backend Environment 
- **Language**: Python 3.13
- **Server Framework**: Flask (REST architecture with Server-Sent Events for real-time logs)
- **Database**: MongoDB (via `pymongo`) for fast, persistent hash lookups and tracking discovery tables.
- **Media Processing**: `opencv-python` (Frame extraction, preprocessing), `yt-dlp` (Stream hydration & video downloading), `imagehash` (Perceptual Hashing)
- **Crawlers**: `httpx`, `asyncio`, and `BeautifulSoup4`

### AI & Neural Layers
- **Core Reasoning Engine**: `deepseek-r1:7b` (Via Ollama/LangChain) - Used for precise metadata topic clustering and analyzing rights compliance.
- **Visual Intelligence**: `llava` - Used to parse out spatial descriptions of individual video frames.
- **Verification Detection**: `ultralytics` (YOLOv8) - High-speed logo and specific object detection used strictly for verifying brand presence in infringing clips.

### Frontend Dashboard
- **Technologies**: Vanilla HTML5, CSS3, JavaScript.
- **Aesthetics**: Glassmorphic, dark-mode, minimalist design featuring robust client-side event listeners processing SSE logs in real-time.

---

## 🚀 Core Workflows

### 1. Ingestion & Preemptive Defense (0-Day Monitor)
- **Watchdog**: The system runs a persistent background loop (`ZeroDayMonitor`) tracking defined authorized channels (e.g., ESPN, Real Madrid Official).
- **Auto-Ingestion**: When a new video uploads, the system downloads it, processes it, and generates perceptual hashes (`phash`) while explicitly cropping out black-boxes to ensure aspect-ratio immunity.
- **Persistent Knowledge**: Hashes are instantly pushed to MongoDB, securing a fingerprint before pirates can react.

### 2. Proactive Piracy Discovery
- **Topic Extraction**: DeepSeek-R1 analyzes the ingested video and extracts 2-3 precise search query topics (e.g., *Real Madrid Champions League Highlights*).
- **Topic Memory Cache**: Extracted topics are checked against an active memory buffer to prevent duplicate queries and rate limits.
- **Parallel Crawl**: The engine concurrently searches **14 domains** (including DuckDuckGo, YouTube, Telegram, VK, TikTok, Reddit, Rumble) utilizing User-Agent rotation and Semaphore batching.
- **Smart Partitioning**: Discovered suspect URLs are grouped in MongoDB explicitly under the *Original Asset* that spawned the hunt, making it easy to track the blast radius of a specific video.

### 3. Deep Scanning & Temporal Fingerprinting
If a suspect link is targeted for a direct scan:
- **Speed Invariant Check**: The comparator evaluates hashes assuming the clip might have been sped up or slowed down by `±10%` to evade basic detections.
- **Overlay Tolerant**: The matching threshold dynamic adjusts to allow passing scores on videos with meme captions or minor overlays.
- **Temporal Window**: A single matched frame is discarded as noise. The engine strictly requires sequential matches grouped across time to confidently declare an infringement.

### 4. AI Compliance & Final Reporting 
- **Multimodal Evaluation**: The suspect video's platform reputation (subscriber counts, verification checks) is piped into DeepSeek-R1 alongside the visual topic contexts. 
- **Rights Gatekeeper**: If the uploader is known in the Authorized Lists or logically deduced as safe, they are passed. Otherwise, they are heavily flagged.
- **Report Generation**: A cohesive file structure is output tracking the Hamming distances of specific timestamps, combining YOLOv8's "Logo confirmation" check with the AI's "Infringement status" in one dashboard.
