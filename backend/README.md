# SeoulFit Backend

FastAPI + LangGraph backend powering the SeoulFit Flutter app.
Self-contained: all AI modules, data, and FAISS vector stores live in this folder.

## Endpoints

- `POST /chat` — conversational trip intake → slot extraction → itinerary (LangGraph + RAG + critic-repair)
- `GET  /state` — current conversation state without invoking the graph
- `POST /reset` — clear a conversation thread
- `POST /analyze-landmark` — Seoul Lens: image → Gemini Vision → seoul.json RAG → English narration
- `POST /nearby` — on-trip help: nearby cafes/restaurants (Google Places, radius expands 500m → 1000m)
- `POST /emergency-rooms` — on-trip help: nearest operating ERs with live bed counts (E-Gen, 60s cache)
- `GET  /healthz`, `GET /lens/health` — health probes

## Setup

```bash
cd seoulfit_flutter/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`.env` holds `GEMINI_API_KEY` / `GOOGLE_API_KEY` (already present), plus `EGEN_API_KEY`
for `/emergency-rooms` — this must be the data.go.kr **Decoding** key; the Encoding key
double-encodes `%` and fails with `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`. Without it,
`/emergency-rooms` silently degrades to the client-side fallback list on every call.

## Re-scraping embassy data

`assets/data/embassies.json` (used by the passport-loss flow) is bundled, not fetched
live. To refresh it from the MOFA directory:

```bash
uv run --with httpx python backend/tools/scrape_mofa.py
uv run python backend/tools/normalize.py
```

## Run

```bash
source venv/bin/activate
uvicorn api:app --reload --port 8000
```

The Flutter app calls `http://localhost:8000` by default. To point at a deployed
backend, build the app with `--dart-define=API_BASE_URL=https://<host>`.
