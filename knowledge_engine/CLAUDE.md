# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Source of truth and current status

- `Doc/文档2.MD` is the authoritative executable spec. Follow its phase boundaries and decision rules when code and docs diverge.
- `README.md` reflects the current implementation status much better than the original scaffold docs: the repo is now implemented through **Phase 10**.
- The backend is no longer just a Phase 0/1 skeleton. The repo now includes upload, ingest, indexing, retrieval, rewrite, answer, replace, soft delete, and eval flows.
- User preference: always run Python-related work inside the project-specific virtual environment / conda environment, never the user’s global Python installation.

## Common commands

## Environment setup

Use a dedicated project environment rather than the system interpreter.

### Conda workflow (preferred when available)

```bash
conda create -n rag_sec_phase1 python=3.11 -y
conda activate rag_sec_phase1
pip install -e ".[test]"
```

If you only need a single command without shell activation, prefer:

```bash
conda run -n rag_sec_phase1 pip install -e ".[test]"
conda run -n rag_sec_phase1 pytest
```

### venv fallback

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -e ".[test]"
```

## Run the backend locally

The Python package is rooted at `backend/`, so run the app from `backend/`:

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

For ingest / replace flows that rely on Celery, the simplest supported path is to bring up the worker and infra with Docker Compose from the repo root:

```bash
docker compose up -d postgres redis qdrant worker
```

Notes:
- `Settings` loads `.env` from the current working directory. Running from `backend/` expects `backend/.env`; Docker Compose avoids that mismatch by injecting environment variables directly.
- `GET /health` is the root liveness probe.
- `GET /api/v1/health/ready` is the dependency-aware readiness probe.

## Run the frontend locally

From `frontend/`:

```bash
npm install
npm run dev
npm run build
npm run preview
```

Default dev URL: `http://localhost:5173`

Frontend env setup:

```bash
cp .env.example .env
```

Default backend target:

```env
VITE_API_BASE_URL=http://localhost:8000
```

Important detail:
- `npm run build` runs `tsc -b && vite build`; there is currently no separate frontend test or lint script.

## Run with Docker Compose

From the repo root:

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f backend
docker compose down
docker compose down -v
```

Useful service targets during backend work:

```bash
docker compose up -d postgres redis qdrant
```

Endpoints after startup:
- API root: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- Qdrant dashboard: `http://localhost:6333/dashboard`

## Database migration commands

From `backend/`:

```bash
alembic upgrade head
alembic downgrade base
```

When using conda without activation:

```bash
conda run -n rag_sec_phase1 bash -lc 'cd backend && alembic upgrade head'
```

## Test commands

From the repo root:

```bash
pytest
pytest -m integration
pytest -m ""
pytest backend/tests/test_health.py
pytest backend/tests/test_health.py::test_health_returns_ok
pytest backend/tests/test_models.py -m integration
pytest backend/tests/test_crud.py -m integration
pytest backend/tests/test_eval_service.py
pytest backend/tests/test_eval_api.py -m integration
pytest backend/tests/test_integration.py::test_health_ready_all_ok -m integration
```

Important details:
- `pyproject.toml` sets `testpaths = ["backend/tests"]`.
- Default pytest options exclude integration tests with `-m 'not integration'`.
- The integration lane is a strict gate: PostgreSQL/Redis/Qdrant unavailability fails rather than skips. Run it against a disposable test database because fixtures migrate and truncate business tables.
- On machines with HTTP proxies, set `NO_PROXY=localhost,127.0.0.1` for local Qdrant/backend tests; otherwise localhost traffic may return a proxy-generated 502.
- Docker backend and worker share `/app/storage`; do not remove that volume mount or give the processes different `STORAGE_ROOT` values.
- `models/` contains only ignored local weights. Deterministic embedding/reranker fallbacks validate orchestration but do not count as real-model quality verification.
- There is currently **no Python lint command configured** in `pyproject.toml`; do not invent Ruff/Black/mypy automation in docs or scripts.
- The frontend `package.json` defines `dev`, `build`, and `preview`, but no frontend test or lint scripts.

## High-level architecture

## Repository shape

- Root holds packaging/orchestration/docs plus the local model assets: `pyproject.toml`, `docker-compose.yml`, `.env.example`, `README.md`, `Doc/`, `models/`, `eval/`, and `frontend/`.
- Backend application code lives under `backend/app/`.
- Alembic lives under `backend/alembic/` and reuses the project `Settings` plus `Base.metadata`.
- Tests live under `backend/tests/` and are split between fast default checks and real infrastructure integration tests.
- `frontend/` is a separate React + TypeScript + Vite MVP that drives the existing FastAPI APIs.

## Runtime layering

The current backend request path is:

1. `backend/app/main.py` creates the FastAPI app, initializes logging, installs CORS, and registers routers.
2. `backend/app/api/*.py` keeps route handlers thin and translates exceptions into structured HTTP responses.
3. `backend/app/services/*.py` contains the actual pipeline logic.
4. `backend/app/models/*.py` and `backend/app/db/*` handle persistence and DB session setup.
5. `backend/app/workers/ingest_worker.py` handles async ingest/update execution through Celery.

Important nuance:
- `backend/app/api/__init__.py` still defines an aggregate router, but `backend/app/main.py` intentionally registers each router explicitly because the current FastAPI version in this repo did not fully expand the aggregated router into concrete `APIRoute`s.

Preserve this split: routes should remain thin, and flow logic should stay in services/workers rather than being pushed upward into the API layer.

## Current implemented system flows

### Upload and ingest flow

The implemented upload/ingest chain is:

upload file → validate extension/MIME/size → compute `file_hash` → save raw file locally → create `document` / `document_version` / `ingest_task` → enqueue Celery task → parse → clean → generate parent/child chunks → persist chunks to PostgreSQL → index **child chunks only** into embedding/Qdrant/FTS → mark task complete

Primary module ownership:
- `app/api/upload.py`: upload endpoint
- `app/services/upload_service.py`: validation, storage, record creation, task dispatch
- `app/workers/ingest_worker.py`: async orchestration
- `app/services/parser_service.py`, `cleaner_service.py`, `chunk_service.py`: content preparation
- `app/services/index_service.py`, `embedding_service.py`, `vector_store.py`, `keyword_store.py`: indexing

### Query flow

The implemented query chain is:

user query → `safety_guard` → `intent_classifier` → `term_expander` → `query_rewriter` → `metadata_filter` construction → vector retrieval + PostgreSQL keyword retrieval → RRF fusion → parent-context reconstruction → `answer_generator` → `citation_checker` → `query_log` persistence

Primary module ownership:
- `app/api/query.py`: `/query/retrieve`, `/query/rewrite`, `/query/answer`
- `app/services/safety_guard.py`: first-stage safety gate
- `app/services/intent_classifier.py`, `term_expander.py`, `query_rewriter.py`, `metadata_filter.py`: query preparation
- `app/services/retriever.py`, `fusion.py`: hybrid retrieval
- `app/services/answer_generator.py`, `citation_checker.py`, `llm_service.py`: grounded answer generation and evidence checking
- `app/prompts/*.md`: prompt templates used by the service layer

### Replace / incremental update flow

The implemented replace/update chain is:

replace upload → validate file and compare `file_hash` with current version → create new `document_version` + `ingest_task` → parse/clean/rechunk new file → diff **child chunks** by `chunk_hash` against current active version → persist new version chunks → embed/index only added child chunks → reuse vectors for unchanged child chunks → deactivate removed chunks in PostgreSQL/Qdrant/FTS → switch `current_version_id`

Primary module ownership:
- `app/api/documents.py`: replace and soft delete endpoints
- `app/services/update_service.py`: chunk diff, vector reuse, soft delete, version switching

### Eval flow

The implemented eval chain is:

load `eval/golden_dataset.jsonl` → materialize `eval_datasets` / `eval_dataset_items` → run real safety/rewrite/retrieve/answer logic per item → compute Recall@K / MRR / citation accuracy / refusal accuracy / average latency → persist `eval_runs` / `eval_run_items`

Primary module ownership:
- `app/api/eval.py`: `/eval/run`
- `app/services/eval_service.py`: dataset loading, per-item execution, metric aggregation, persistence
- `eval/golden_dataset.jsonl`: default dataset source

## Database and indexing architecture

The core persistence/indexing model established across the implemented phases:

- PostgreSQL is the source of truth for documents, versions, chunks, ingest tasks, query logs, feedback, and eval data.
- `backend/app/models/__init__.py` imports all ORM models so Alembic can discover metadata.
- UUID primary keys are used throughout.
- JSONB fields have explicit defaults on both ORM and migration sides.
- `chunks.search_tsv` stores PostgreSQL FTS content.
- Qdrant is used for vector search over active child chunks.
- Parent chunks are stored for context reconstruction, not for direct vector/keyword retrieval.
- Soft delete and replace flows must keep PostgreSQL visibility, FTS visibility, and Qdrant visibility aligned.

## Non-obvious implementation rules

These are easy to violate if you only skim file names:

- Implement according to the spec’s phase boundaries; many modules were scaffolded before they were fully implemented.
- API routes should stay thin; do not move pipeline logic into route handlers.
- Uploading a file creates a new `document`; creating a new version is a separate replace flow.
- Incremental updates are chunk-diff based, not full reindex by default.
- Only **child chunks** should be embedded and exposed to vector/keyword retrieval; parent chunks are for answer-context reconstruction.
- Safety filtering is the first query step, not a post-processing step.
- Retrieval defaults should honor active document/version/chunk visibility.
- When working on eval, reuse the real query pipeline instead of inventing a disconnected mock evaluation path.

## Testing structure

Tests are intentionally layered:
- `backend/tests/test_health.py`: HTTP contract checks without live infra
- `backend/tests/test_config.py`: settings/bootstrap assertions
- `backend/tests/test_integration.py`: infrastructure readiness checks
- `backend/tests/test_models.py`: schema/defaults/constraint coverage
- `backend/tests/test_crud.py`: persistence helper coverage
- `backend/tests/test_ingest_worker.py`: ingest/index pipeline behavior
- `backend/tests/test_eval_service.py`: eval logic
- `backend/tests/test_eval_api.py`: eval endpoint integration behavior
- `backend/tests/conftest.py`: shared fixtures, DB migration/session setup

Keep new tests aligned with this split: prefer fast default tests, and mark tests `integration` when they require real PostgreSQL/Redis/Qdrant.
