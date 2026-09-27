# Manifestation Board

A drag-and-drop project board app: freeform, resizable boards with tasks and
per-board AI chat. Frontend is Node.js/Express, backend is Python/FastAPI,
data lives in MongoDB.

## Setup

```bash
cp backend/.env.example backend/.env
# edit backend/.env and set ANTHROPIC_API_KEY (needed for the per-board chat)
```

## Run

```bash
docker compose up
```

- App: http://localhost:3000
- API directly: http://localhost:8000/api
- Mongo: localhost:27017

Both `backend/app` and the whole `frontend` folder are bind-mounted into
their containers, and both run with auto-reload (`uvicorn --reload`,
`nodemon`), so code edits apply immediately — no rebuild or restart needed.
Only changes to `requirements.txt` / `package.json` or the Dockerfiles
require `docker compose up --build`.

## Layout

```
backend/    FastAPI app, MongoDB access, PDF export, Anthropic chat calls
frontend/   Express static server + /api proxy, the Manifestation Board UI (public/)
```
