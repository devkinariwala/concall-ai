# ConcallAI

Real-time AI pipeline that monitors NSE and BSE corporate announcements for Indian listed companies, downloads quarterly earnings conference-call ("concall") transcript PDFs, extracts and cleans the text, generates strictly evidence-backed structured summaries using Google Gemini, and streams results via a FastAPI REST API, WebSocket feed, and React dashboard.

---

## Architecture

```text
[1. Watch & Ingest]        [2. Extract & Clean]       [3. AI Summarize & Verify]      [4. Serve & Stream]
NSE / BSE APIs      --->   PyMuPDF ([PAGE N])  --->   Chunked Gemini Extraction --->  FastAPI REST API
Fingerprint Dedup          Text Cleaning              Verbatim Quote + Page           WebSocket (/ws/summaries)
SQLite State               12k Char Chunking          Double Validation + Checkpoints Minimal React Dashboard
```

### Key Design Decisions
- **Zero-Hallucination Evidence Verification:** Every extracted fact (`EvidenceClaim`), analyst exchange (`QAItem`), and risk (`RiskItem`) requires a verbatim quote (>=15 chars) and an exact `[PAGE N]` match verified programmatically against the full original transcript at both chunk level and final summary level.
- **Map-Reduce Chunking + Atomic Checkpointing:** Long transcripts (15-48 pages) are split into ~12,000-character chunks with a 1,000-character overlap. Each chunk is extracted independently, validated, and saved atomically (`backend/data/summaries/checkpoints/`). Transient API errors (`503` / rate limits) resume from the last completed chunk without repeating prior work.
- **Structured Q&A & Risk Attribution:** Analyst Q&A pairs are modeled separately from flat facts, and risks explicitly distinguish `management_acknowledged`, `analyst_raised`, and `inferred_from_discussion` so analyst questions are never misrepresented as confirmed company risks.
- **Unattended Real-Time Loop with Error Isolation:** FastAPI's `lifespan` runs `start_background_monitor()` on `POLL_INTERVAL_SECONDS` inside worker threads (`asyncio.to_thread`). Ingestion, PDF extraction, and summarization are each wrapped in per-file `try/except` blocks so one bad PDF or exchange error never stalls the rest of the queue.
- **Source Provenance:** Each summary JSON includes `scrip_code`, `source` (`NSE`/`BSE`), and `source_url` traced from `IngestionState` (SQLite).

---

## Quick Start (Cross-Platform)

### 1. Prerequisites
- Python 3.12+
- Node.js 20+ and npm
- A Google Gemini API key

### 2. Setup
```powershell
git clone <your-repo-url>
cd concall-ai

# Backend virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # macOS/Linux: source .venv/bin/activate
pip install -r backend\requirements.txt

# Environment variables
Copy-Item .env.example .env       # macOS/Linux: cp .env.example .env
# Edit .env and set GEMINI_API_KEY

# Frontend dependencies
cd frontend
npm install
cd ..
```

### 3. Run Everything (One Command)
```powershell
python start.py
```
*(Windows PowerShell users can also run `.\start.ps1`.)*

This launches:
- **FastAPI Backend + Background Watcher + WebSocket:** `http://localhost:8000` (Swagger Docs: `http://localhost:8000/docs`)
- **React Dashboard:** `http://localhost:5173`

---

## API & WebSocket Endpoints

| Method / Protocol | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Service health and active Gemini model |
| `GET` | `/api/companies` | Configured companies with transcript/summary counts |
| `GET` | `/api/transcripts` | Extracted transcripts (optional `?symbol=HDFCBANK`) |
| `GET` | `/api/summaries` | Generated summaries metadata (optional `?symbol=HDFCBANK`) |
| `GET` | `/api/summaries/{id}` | Full structured JSON summary |
| `GET` | `/api/summaries/{id}/markdown` | Human-readable Markdown summary |
| `GET` | `/api/status` | Pipeline run state and active WebSocket clients |
| `POST` | `/api/pipeline/trigger` | Manually trigger background summarization |
| `WS` | `/ws/summaries` | Real-time JSON event stream (`connected`, `download_completed`, `extraction_completed`, `summary_completed`, `processing_failed`) |

---

## Sample Outputs

Included in `samples/` (raw transcript PDF, structured JSON, and Markdown summary):
- `samples/HDFCBANK/` - HDFC Bank Limited (Q2 FY27)
- samples/INFY/ - Infosys Limited
- samples/MARUTI/ - Maruti Suzuki India Limited
- `samples/RELIANCE/` - Reliance Industries Limited
- `samples/SUNPHARMA/` - Sun Pharmaceutical Industries Limited

---

## What I'd Do With More Time
1. **OCR Fallback:** Add Tesseract/PaddleOCR for scanned image-only PDFs.
2. **XBRL Parsing:** Parse exchange XBRL XML attachments directly for guaranteed scrip code, event type, and call date metadata.
3. **Audio-Only Handling:** Detect audio-only intimations and optionally transcribe via Whisper when written transcripts are delayed.
4. **PostgreSQL + Redis Pub/Sub:** Move from SQLite and in-memory WebSocket state to PostgreSQL and Redis for multi-worker horizontal scaling.
5. **Backfill CLI Mode:** Add a date-range backfill command to pull historical quarters on demand.

See [LIMITATIONS.md](LIMITATIONS.md) for detailed trade-offs and known issues.

