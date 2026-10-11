# SATYAM AI - Multimodal Media Authenticity (MVP)

Explainable media checks for images, sampled video frames, and audio. It reports uncertainty honestly: unavailable checks are labelled unavailable, raw model output is never presented as a calibrated probability, and model scores are shown only when a configured model actually returns them.

## Run it
```bash
# Backend (Python 3.10+)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional; export the variables or load them with your shell
uvicorn app.main:app --reload --port 8000

# Frontend (Node 18+)
cd frontend && npm install && npm run dev      # http://localhost:5173 (proxies /api to :8000)
```

## Open the frontend by double-clicking
The source `frontend/index.html` needs Vite to compile the React/TypeScript app, so it cannot be opened directly. Build the standalone page, then double-click `frontend/dist/index.html`:
```bash
cd frontend
npm install
npm run build
```
The built page renders when opened from disk. For uploads and analysis, first double-click `start-backend.bat` in the project folder and keep its window open, then open `frontend/dist/index.html`. The first launch creates a Python virtual environment and installs the backend dependencies. The launcher permits the browser's `null` file origin; this origin is shared by local files and other opaque browser origins, so the API is bound to localhost and the permission is set only for that launcher.

## Enable the AI model (optional)
Create `backend/.env` from `.env.example` and set model IDs, revisions, and the exact class labels used by those models:
```bash
cd backend
cp .env.example .env
pip install -r requirements-ml.txt
# Edit .env: SATYAM_HF_MODEL, SATYAM_AUDIO_MODEL and label mappings
```
Set model revisions to immutable commit hashes where possible. Check each model card for its task, input format, labels, license, training data and known weaknesses before use. Weights download on first run (needs internet). The audio adapter accepts raw class scores only; it does not infer voice cloning, transcribe, or validate the model. Scores are uncalibrated and the project has not measured model accuracy. Configure label mappings to match the selected model exactly. Audio is decoded with libsndfile or FFmpeg. Swap models by changing these variables, or add an adapter in `app/models/model_registry.py`. Attribute the model per its license.

Audio uploads are capped at 30 MB and 180 seconds by default. The backend decodes and segments supported audio for inference; when the optional audio model is not configured, the report explicitly marks the classifier unavailable and does not invent scores. The API also exposes `GET /api/analysis/history` for recent saved reports.

## Tests and evaluation
```bash
cd backend && python -m unittest discover -s tests -v     # API tests skip if fastapi/httpx are missing
python scripts/evaluate.py data/                          # data/real/* and data/fake/*; prints FP/FN and class balance
```

## Build a labeled multimodal dataset

The preparation pipeline reads **local media plus source annotations**; it does not download datasets, infer labels from filenames, synthesize records, or fill missing model scores. Put a CSV manifest at `dataset/annotations.csv` in the project root. Paths in `file_path` are relative to that manifest or absolute. One row describes one actual media file:

```csv
file_path,media_type,authenticity_label,manipulation_type,source_dataset,source_url,license,label_source,label_confidence,split_group
media/image-001.png,image,AI_GENERATED,text-to-image,example-dataset,https://example.org/docs,review applicable terms,verified annotation record,1.0,source-item-001
```

The example is a **format illustration, not a real sample or annotation**. Only use records with labels and provenance verified against the source's documentation. `split_group` should be the source's identity/sequence/original-media group shared by related originals and derivatives; the pipeline keeps each group in one split. Without it, only exact file hashes are grouped, so related files may still leak across splits.

From the project root, run:

```bash
python backend/scripts/prepare_dataset.py
```

This writes `satyam_ai_dataset.csv`, `dataset_schema.csv`, `dataset_summary.csv`, and `dataset_validation_report.txt` to the project root. The default modality targets are 4,000 images, 3,000 videos, and 3,000 audio samples. It selects genuine, unique records up to those caps and reports shortfalls; it does not oversample or fabricate. Invalid files and conflicting labels for identical hashes are excluded and described in the report. Feature extraction is incremental for audio and samples at most 12 video frames per file.

Optional, explicitly requested image/video-frame/audio classifier inference can be run with `--run-configured-models` after configuring compatible models in `backend/.env` and installing `backend/requirements-ml.txt`. Outputs are raw model labels/scores, not calibrated probabilities. A frame-flag ratio is not a video-level probability. Temporal inconsistency, lip-sync, voice-cloning and calibrated three-class probabilities remain blank because this project has no validated detectors for those outputs. Ordinary signal features are descriptive, not proof of synthetic media.

The inspected public candidate datasets are [FaceForensics++](https://github.com/ondyari/FaceForensics), [DFDC](https://ai.meta.com/datasets/dfdc/), [Celeb-DF](https://github.com/yuezunli/celeb-deepfakeforensics), [GenImage](https://github.com/GenImage-Dataset/GenImage), and [WaveFake](https://github.com/RUB-SysSec/WaveFake). No dataset was downloaded or included: FaceForensics++/DFDC/Celeb-DF have access workflows or terms to follow; verify the current license and redistribution permission for every source before processing or sharing. These sources do not, by themselves, guarantee the target's full class coverage: several video datasets focus on face manipulation, GenImage is an image real-vs-generated benchmark, and WaveFake covers generated audio rather than every form of genuine-audio manipulation or voice cloning.

This pipeline prepares and validates records; it does **not** train a model. No training set, evaluation result, or trained artifact is claimed. Do not train a production detector from metadata/statistics alone or feed label/provenance/hash/split columns as input features. A future trainer must use modality-appropriate media features, group-held-out splits, a documented supported label taxonomy, and an independent evaluation set before its model is wired into the existing inference adapters.

## Example
```bash
curl -F file=@photo.jpg localhost:8000/api/analyze/image
curl -F file=@sample.wav localhost:8000/api/analyze/audio
curl -F file=@clip.mp4 localhost:8000/api/analyze/video
curl localhost:8000/api/analysis/<id>/report -o report.json
curl localhost:8000/api/analysis/<id>/report.pdf -o report.pdf
curl localhost:8000/api/analysis/history
curl -X DELETE localhost:8000/api/analysis/<id>
```
Responses follow `backend/app/schemas/analysis.py` (modules with status/stance/limitations, plus `fusion`).

## Status
**Implemented:** magic-byte and extension validation, size/duration caps, SHA-256, image metadata and JPEG observations, sampled video-frame checks, separate audio-track extraction, bounded audio decoding/segmentation, configurable image/audio model adapters, SQLite analysis history, JSON/PDF reports, score visualizations for actual model class scores, rate limiting, CORS and temporary-file cleanup.
**Model status:** no detector is bundled or preconfigured. Until a compatible, licensed model is selected and configured, its modality is explicitly marked unavailable. No model accuracy or calibrated probabilities are claimed. Video uses sampled frames, not a temporal deepfake model.
**Not implemented:** face tracking, temporal/lip-sync analysis, audio-visual synchronization detection, localized edit overlays, C2PA, authentication, queued background jobs, live web search, or probability calibration. History is for a single local instance and stored results have no per-user access control.
**Validation:** backend unit/API tests and frontend production build pass. No representative authentic/manipulated media evaluation set has been tested; do not treat output as forensic proof.

## Deploy (student hackathon)
Backend: any VM or Render/Railway with `uvicorn app.main:app --host 0.0.0.0`, set `SATYAM_ENV=production` and `SATYAM_CORS_ORIGINS` to your frontend URL. Frontend: `npm run build`, host `dist/` (Netlify/Vercel) with `VITE_API_BASE` pointing at the backend. The in-memory rate limiter and SQLite suit a single instance only.
