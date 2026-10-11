# SATYAM AI - Multimodal Media Authenticity Detection

Explainable media checks for images, sampled video frames, and audio. It reports uncertainty honestly: unavailable checks are labelled unavailable, raw model output is never presented as a calibrated probability, and model scores are shown only when a configured model actually returns them.

## Key Features

- **Multimodal Tamper Verification**: Inspects images (magic bytes, EXIF, JPEG recompression grid), video (sampled keyframe extraction, brightness/sharpness metrics), and audio (WAV/MP3/M4A/FLAC/OGG header validation, bounded decoding, segment windowing).
- **Interactive Audio Waveform Visualizer**: Client-side Web Audio API amplitude rendering with interactive seek-and-playhead synchronization and segment boundaries.
- **Sampled Video Frame Player Sync**: Click any sampled frame timestamp to instantly seek the video player to that exact moment for forensic inspection.
- **Explainable AI & Stance Badges**: Findings clearly explain what they mean, innocence explanations, model versioning, and known limitations.
- **Resumable Chunked Uploads**: Fault-tolerant chunk upload with SHA-256 verification, transfer speed indicators, retry handling, and offline auto-resume.
- **Investigation History & Management**: Full-text search, media type filters (All, Image, Video, Audio), assessment filters, sort order, and direct PDF/JSON export.
- **Challenge Card 2 User Feedback System**: Integrated modal and rate-limited API (`POST /api/feedback`) for gathering structured user experience and forensic explainability feedback.
- **Database & Security Hardening**: SQLite WAL mode with 30s busy timeout, foreign key enforcement, constant-time dummy authentication checks (mitigating user enumeration/timing attacks), and session cleanup.

## Quick Start

### 1. Start the Backend (Python 3.10+)
```bash
cd backend
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env            # optional
uvicorn app.main:app --reload --port 8000
```
*Tip: On Windows, you can simply double-click `start-backend.bat` in the project root.*

### 2. Start the Frontend (Node 18+)
```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxies /api to http://localhost:8000)
```

## Standalone Frontend (Double-Click Launch)
Build the production bundle and open `frontend/dist/index.html` directly in any browser:
```bash
cd frontend
npm run build
```
For uploads and analysis when opening `frontend/dist/index.html` from disk, first start `start-backend.bat` and leave its window open.

## Enable Optional AI Models
Create `backend/.env` from `.env.example` and set model IDs, revisions, and the exact class labels used by those models:
```bash
cd backend
cp .env.example .env
pip install -r requirements-ml.txt
# Edit .env: SATYAM_HF_MODEL, SATYAM_AUDIO_MODEL and label mappings
```
Set model revisions to immutable commit hashes where possible. Check each model card for its task, input format, labels, license, training data, and known weaknesses before use. The audio adapter accepts raw class scores only; it does not infer voice cloning or transcribe. Scores are uncalibrated and the project has not measured model accuracy. Configure label mappings to match the selected model exactly. Audio is decoded with libsndfile or FFmpeg.

Audio uploads are capped at 30 MB and 180 seconds by default. The backend decodes and segments supported audio for inference; when the optional audio model is not configured, the report explicitly marks the classifier unavailable and does not invent scores.

## API Reference

### Media Analysis
- `POST /api/analyze/image` - Analyze an image file
- `POST /api/analyze/video` - Analyze a video file (samples keyframes)
- `POST /api/analyze/audio` - Analyze an audio file (segment windowing)
- `GET /api/analysis/{id}` - Fetch investigation result
- `GET /api/analysis/{id}/report` - Download report in JSON format
- `GET /api/analysis/{id}/report.pdf` - Download forensic report in PDF format
- `GET /api/analysis/history` - List user's investigation history
- `DELETE /api/analysis/{id}` - Delete investigation

### Chunked Resumable Uploads
- `POST /api/uploads/initiate` - Start resumable chunk upload session
- `PUT /api/uploads/{upload_id}/chunks/{chunk_index}` - Upload individual binary chunk
- `GET /api/uploads/{upload_id}` - Check uploaded chunks status
- `POST /api/uploads/{upload_id}/complete` - Finalize assembly and initiate analysis
- `DELETE /api/uploads/{upload_id}` - Cancel and purge upload chunks

### Challenge Card 2 Feedback & Evaluation
- `POST /api/feedback` - Submit evaluation rating (1-5), role, expectations, likes, confusion, bugs, and suggestions (rate limited to 5 req/min)
- `GET /api/feedback` - Review submitted feedback records (authenticated)

### Authentication
- `POST /api/auth/register` - Create user account
- `POST /api/auth/login` - Sign in and receive session token
- `POST /api/auth/logout` - Invalidate session
- `GET /api/auth/me` - Validate session token

## Build a Labeled Multimodal Dataset

The preparation pipeline reads **local media plus source annotations**; it does not download datasets, infer labels from filenames, synthesize records, or fill missing model scores. Put a CSV manifest at `dataset/annotations.csv` in the project root. Paths in `file_path` are relative to that manifest or absolute:

```csv
file_path,media_type,authenticity_label,manipulation_type,source_dataset,source_url,license,label_source,label_confidence,split_group
media/image-001.png,image,AI_GENERATED,text-to-image,example-dataset,https://example.org/docs,review applicable terms,verified annotation record,1.0,source-item-001
```

From the project root, run:
```bash
python backend/scripts/prepare_dataset.py
```
This writes `satyam_ai_dataset.csv`, `dataset_schema.csv`, `dataset_summary.csv`, and `dataset_validation_report.txt` to the project root.

## Verification & Tests

Run the backend test suite:
```bash
cd backend
python -m pytest tests -v
```
All 42 backend unit, integration, and security tests pass.

Run the frontend production build:
```bash
cd frontend
npm run build
```
Builds cleanly with zero TypeScript or Vite errors into `dist/`.

## Status & Forensic Disclaimers

- **Implemented**: Magic-byte and extension validation, size/duration limits, SHA-256 fingerprinting, image metadata & JPEG grid analysis, sampled video-frame checks with timestamp synchronization, audio amplitude waveform visualizer with segment timeline, configurable Hugging Face image/audio model adapters, SQLite analysis history with full-text search and filtering, JSON/PDF forensic exports, Challenge Card 2 feedback system, constant-time auth security, and rate limiting.
- **Model Status**: No AI classifier is bundled or preconfigured. Until a compatible, licensed model is configured, model-dependent checks are explicitly reported as unavailable. No model accuracy or calibrated probabilities are claimed. Video analysis evaluates sampled frames only, not temporal face-warp deepfake continuity.
- **Ethical & Forensic Notice**: AI authenticity detection is inherently probabilistic. Automated forensics cannot prove authenticity or determine real-world human context; treat findings as evidentiary clues rather than definitive proof.
