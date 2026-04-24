# Digital Asset Protection System (DAP)

An AI-driven **Digital Asset Protection** system for detecting unauthorized use of sports media content using **Perceptual Hashing (pHash)** and **YOLOv8 object detection**.

---

## Architecture

```
Asset Protection/
├── core/
│   ├── hasher.py      # Keyframe extraction + pHash (OpenCV + imagehash)
│   ├── detector.py    # Hamming distance comparison engine
│   └── verifier.py    # YOLOv8 logo/watermark detection
├── pipeline/
│   ├── ingestor.py    # Phase 1 — Ingest directories of official clips
│   ├── monitor.py     # Phase 2/3 — Web crawler simulation + AI verification
│   └── reporter.py    # Phase 4 — Generate terminal + JSON reports
├── data/
│   └── hash_db.json   # Persistent hash database (auto-created)
├── reports/           # JSON report output directory
├── main.py            # CLI entry point
└── requirements.txt
```

---

## Installation

```bash
pip install -r requirements.txt
```

> YOLOv8 weights (`yolov8n.pt`) are downloaded automatically on first use.

---

## How It Works

### The Math

```
Hash_Original = 11001010 10110101 ...   (256-bit pHash)
Hash_Pirated  = 11001011 10110101 ...

Hamming Distance (D_H) = count of differing bits

D_H ≈ 0          →  Direct copy
0 < D_H < 8      →  Modified version (re-encoded / resized)
D_H ≥ 8          →  Likely different content
```

### Pipeline Phases

| Phase | Module | Description |
|---|---|---|
| 1 — Ingestion | `ingestor.py` | Hash all official clips → `hash_db.json` |
| 2 — Detection | `monitor.py` | Extract + compare suspect frames (Hamming) |
| 3 — Verification | `verifier.py` | YOLOv8 logo/watermark check on matched frames |
| 4 — Reporting | `reporter.py` | Rich terminal table + JSON report |

---

## Usage

### Phase 1 — Ingest official clips

```bash
python main.py ingest --clips-dir ./official_clips
```

Hashes every video in the folder and stores fingerprints in `data/hash_db.json`.

### Phase 2-4 — Scan a suspect video

```bash
python main.py scan --suspect ./pirated_video.mp4
```

Compares the suspect video against the database, runs YOLO on matches, and outputs a full report.

### Full Pipeline (Ingest + Scan)

```bash
python main.py full --clips-dir ./official_clips --suspect ./pirated_video.mp4
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--threshold N` | `8` | Hamming distance cutoff for a match |
| `--interval SEC` | `2.0` | Seconds between sampled keyframes |
| `--db PATH` | `data/hash_db.json` | Hash database location |
| `--no-yolo` | off | Skip YOLOv8 verification (faster) |
| `--yolo-model` | `yolov8n.pt` | YOLO weights file |
| `--overwrite` | off | Re-hash clips already in the database |

---

## Sample Output

```
Phase 4 — Similarity Report
┌─────────────┬──────────┬─────────────────┬────────────┬───────────────┬──────────────────────────┐
│ Suspect Time│ Best D_H │ Matched Clip     │ Match Time │ Logo Detected │ Flag Status              │
├─────────────┼──────────┼─────────────────┼────────────┼───────────────┼──────────────────────────┤
│   00:02     │    2     │ match_v1.mp4     │   00:02    │ YES (78%)     │ 🚨 CONFIRMED INFRINGEMENT│
│   00:04     │    3     │ match_v1.mp4     │   00:04    │ YES (81%)     │ 🚨 CONFIRMED INFRINGEMENT│
│   00:06     │   14     │ other_clip.mp4   │   00:10    │ No            │ ✅ CLEAR                 │
└─────────────┴──────────┴─────────────────┴────────────┴───────────────┴──────────────────────────┘

 Similarity Score:  66.67%
 VERDICT:           MODERATE SIMILARITY — Possible Modified Copy
```

---

## Verdict Thresholds

| Similarity % | Verdict |
|---|---|
| ≥ 80% | HIGH SIMILARITY — Likely Unauthorized Copy |
| 40–79% | MODERATE SIMILARITY — Possible Modified Copy |
| 10–39% | LOW SIMILARITY — Minor Overlap Detected |
| < 10% | NO SIGNIFICANT MATCH — Content Appears Original |
