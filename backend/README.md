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
- `POST /nearby-poi` — on-trip help: nearby sights (한국관광공사 `locationBasedList2`, 10min cache,
  falls back to `dataset/tour_poi.json` if the API is down)
- `POST /nearby-shopping` — on-trip help: nearby shopping (Visit Seoul, pre-collected)
- `POST /events` — Seoul festivals, performances and exhibitions (한국관광공사
  `searchFestival2` + `areaBasedList2`, merged and cached 10min)
- `POST /poi-summary`, `/poi-detail`, `/poi-image` — a stop's blurb, visitor info and photo.
  한국관광공사 `detailCommon2`/`detailImage2` where the place is in their DB, Tavily + Gemini
  (and Google Places) for everything else
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

data.go.kr issues one key per account and each service is approved against it, so the
same `EGEN_API_KEY` also authenticates 한국관광공사 TourAPI (`tourapi.py`) — no separate
key is needed. Set `TOURAPI_KEY` only to point TourAPI at a different account; it wins
when present. Without either, `/events` serves an empty list and `/nearby-poi` falls
back to the pre-collected snapshot, both without erroring.

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
uvicorn api:app --reload --port 8000 --no-proxy-headers
```

`--no-proxy-headers` is not optional. uvicorn's ProxyHeadersMiddleware is on by
default and rewrites `request.client.host` from the **first** `X-Forwarded-For`
hop — the one the client supplies and can therefore forge. The rate limiter
buckets on that value, so leaving it on lets `-H 'X-Forwarded-For: <random>'`
get a fresh quota on every request. Measured: with it on, eight requests against
a limit of five all returned 200; with it off, the sixth returned 429.

Set `TRUST_PROXY=0` as well when the API is exposed directly rather than behind
a TLS-terminating proxy. Behind exactly one proxy (Render, Fly, Cloud Run),
leave it at the default: `_client_ip` then reads the **last** hop, which is the
one your own proxy appended and the client cannot control.

## Deploy checklist

| | |
|---|---|
| `FRONTEND_ORIGIN` | the deployed web origin, comma-separated. Never `*` — the app refuses to start. Unset means localhost-only, and the deployed frontend is CORS-blocked. |
| `TRUST_PROXY` | `1` behind a proxy (default), `0` when exposed directly |
| uvicorn flags | `--no-proxy-headers`, and **one worker only** — the LangGraph `MemorySaver` is per-process, so a second worker resets conversations at random |
| Flutter build | `flutter build web --dart-define=API_BASE_URL=https://<api-host>` |
| Keep warm | cold start is ~14s / ~336MB RSS; ping `/healthz` every 10 min so no judge eats that |

The Flutter app calls `http://localhost:8000` by default. To point at a deployed
backend, build the app with `--dart-define=API_BASE_URL=https://<host>`.
