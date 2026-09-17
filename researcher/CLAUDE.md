# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-agent deep research system. Backend: Python 3.13 / FastAPI / LangGraph. Frontend: Vue 3 / TypeScript / Vite / Element Plus. The system runs parallel AI agents (planner, searcher, reader, analyzer, critic, writer, validator, synthesizer) orchestrated through two LangGraph StateGraph topologies (hierarchical, debate) to produce structured research reports with evidence-backed claims.

## Commands

### Backend (run from `deep_research_system/`)
```bash
# Start dev server
python main.py
# or
uvicorn main:app --reload --port 8000

# Run all tests
python -m pytest tests/ -v

# Run single test file
python -m pytest tests/test_report_validator.py -v

# Check Python syntax (no import dependencies needed)
python -c "import ast; ast.parse(open('app/topology/hierarchical.py').read())"
```

### Frontend (run from `deep_research_system/frontend/`)
```bash
npm run dev          # Vite dev server
npm run build        # vue-tsc + vite build
npx vue-tsc --noEmit # Type-check only
```

## Architecture

### LangGraph Orchestration (`app/graphs/`)

The topology orchestration uses LangGraph `StateGraph` with a `GraphContext` TypedDict as the graph state. The Pydantic `ResearchState` is nested inside `context["state"]`. **The `on_event` callback is passed through `GraphContext` (not stored as a mutable instance field)** so concurrent task executions don't interfere with each other.

```
GraphContext = {
    "state": ResearchState,           # the Pydantic state model
    "on_event": EventCallback | None, # event callback for SSE streaming
    "last_validation": dict,          # validator output from last run
    "supplementary_result": dict | None,
    "repair_attempt": int,
    "supplementary_loop_count": int,
    "last_plan_result": dict,         # debate topology only
}
```

Key files:
- `hierarchical_graph.py` — `HierarchicalGraphRunner`: planner → search(parallel) → reader(parallel) → analyzer → critic → [supplementary_search → analyzer] loop → writer → validator → [repair_writer → validator] loop
- `debate_graph.py` — `DebateGraphRunner`: planner → debate(parallel branches) → critic → synthesizer → writer → validator → [repair_writer → validator] loop
- `events.py` — `emit(on_event, event)` and `wrap_agent_name(on_event, name)` helpers. `wrap_agent_name` returns a callback that renames agent-level events for subtask nodes.
- `graph_state.py` — `GraphContext` TypedDict definition with `EventCallback` type alias
- `factory.py` / `nodes.py` — Alternative factory and reusable node runner patterns (WIP, not yet the primary code path)

### Topology Layer (`app/topology/`)

Now a **thin delegation layer** wrapping the graph runners:
- `HierarchicalTopology` / `DebateTopology` — lazily instantiate their graph runner then delegate `execute()` → `runner.run()`
- `router.py` — Routes `task_type` to topology (hierarchical or debate)
- `base.py` — `BaseTopology` ABC with a static `emit()` helper

### Backend Service Layer

**`ResearchService`** manages the full task lifecycle:
- `create_task()` spawns `asyncio.create_task(self._execute(...))` and returns immediately (async). `create_task_sync()` awaits completion.
- `_execute()` creates a fresh `ResearchState`, defines an `on_topology_event` closure that stamps `task_id` on events and routes them to SSE subscriber queues, then calls the topology.
- `cancel_task()` calls `asyncio.Task.cancel()` on the running handle. `_execute` catches `CancelledError` and emits a terminal event.
- `subscribe()`/`unsubscribe()`/`_emit()` — per-task `asyncio.Queue` instances for SSE broadcasting.
- `_cache` — simple MD5-based in-memory cache keyed by `md5(user_query)`. The cache key ignores depth/budget parameters.
- `initialize()` — marks orphaned `RUNNING` tasks in Redis as `FAILED` on startup.

**`TaskStateStore`** (`app/services/task_state_store.py`) — Redis-backed persistence:
- Task states stored at `research:task:{task_id}:state`, events at `research:task:{task_id}:events`
- 7-day TTL for state, 3-day for events. `search_tasks()` queries by status.
- Used as fallback by `get_task()` and `get_all_tasks()` when in-memory data is unavailable.

### API Layer (`app/api/`)

- `routes_research.py` — `POST /research` (create async), `POST /research/sync` (blocking), `GET /research` (list), `GET /research/{id}` (poll), `GET /research/{id}/stream` (SSE), `POST /research/{id}/cancel`, `DELETE /research/{id}`
- SSE endpoint: subscribes an `asyncio.Queue`, yields events as SSE `data:` lines, sends `: keepalive\n\n` every 30s, breaks on `done`/`cancelled`/`error`

### Model Pool (`app/model_pool/`)

- `ModelRegistry` — loads model definitions from `config/models.yaml`
- `FallbackRouter` — selects models by capability/cost/latency requirements
- `APIKeyPool` — manages API keys per model, `KeyCircuitBreaker` tracks failures per key
- `LLMClient` — shared `httpx.AsyncClient` for streaming LLM calls with retry

### Agents (`app/agents/`)

Each agent extends `BaseAgent`. `BaseAgent.run()` selects model → streams LLM response → parses JSON output → emits events. Agents declare `TaskRequirement` (model slot, capabilities, cost tier) for the model router. Sub-task agents (Searcher, Reader, Debate) are created fresh per sub-question via factory functions; top-level agents (Planner, Analyzer, Critic, Writer, Validator) are shared singletons on the graph runner.

### Frontend Multi-Session Architecture

The Pinia store (`stores/research.ts`) supports **multiple concurrent sessions**:

- `sessions: Record<string, ResearchSession>` — all sessions keyed by task_id
- `sessionOrder: string[]` — ordered list (newest first)
- `activeSessionId: string | null` — which session the UI is currently viewing
- `draftSession: ResearchSession | null` — unsaved "new session" draft (keyed as `"draft:new"`)
- Last active session persisted to `localStorage` key `"deep-research:last-active-task-id"`
- Each session independently manages its own SSE `EventSource`, polling interval, and token buffer. Creating a new session does not stop existing sessions — they run to completion independently.

**Key components:**
- `SessionSidebar.vue` — lists sessions with status badges, delete (disabled for running), new session button
- `ResearchForm.vue` — query input with task type/depth selection, syncs form on draft selection
- `TopologyGraph.vue` — VueFlow canvas rendering agent nodes with real-time status. Dynamically injects subtask nodes (`searcher_{id}`, `reader_{id}`) with collision-avoidant positioning.
- `DetailPanel.vue` — per-agent structured output viewer
- `ReportViewer.vue` — renders final report sections
- Export to Markdown/PDF/Word via `utils/export.ts`

### Data Flow for a Research Task

1. Frontend POSTs `/research` → gets `task_id`
2. Frontend opens SSE to `/research/{id}/stream`
3. Backend `ResearchService._execute()` creates a per-task `on_topology_event` closure, calls topology with it
4. Graph nodes emit events via `emit(on_event, ...)` → closure stamps `task_id` → `_emit()` pushes to subscriber queues
5. Frontend store routes events: `stage_start/complete` → nodeStates, `agent_stream_token` → buffered (50ms flush), `report_update` → result.report, `done` → final result
6. After topology completes, backend emits `done` with `{report, claim_graph, metrics, audit_trail}`

### Key Patterns

- **`on_event` in GraphContext**: The event callback is passed through `GraphContext["on_event"]`, NOT stored as a mutable instance field. Each `run()` call creates its own context dict, making concurrent task executions safe.
- **Parallel sub-tasks**: Graph nodes create separate agent instances per sub-question/hypothesis, run via `asyncio.gather`, emit events with subtask-specific agent names (`searcher_{id}`, dynamic `h_{index}`)
- **Event wrapping**: `wrap_agent_name(on_event, agent_name)` renames agent events for subtask/composite nodes
- **Repair loop**: Writer → Validator → if score < 85, re-run writer with `repair_context`. Max 2 attempts. Each repair uses unique name `repair_writer_{N}`. Validator runs with `on_event=None` during repair.
- **Supplementary search loop**: Critic → if `needs_more_research`, run searcher with suggested queries → re-analyze → re-critic. Max 1 loop.
- **Token streaming**: LLM streams tokens → `agent_stream_token` events → frontend buffers per agent → flushes every 50ms
- **Deterministic validation**: `report_validator.py` runs code-level checks before the LLM validator. Fails fast on high-severity issues.

### Config Files (`config/`)

- `app.yaml` — App settings, cost estimates, search provider
- `models.yaml` — Model registry (6 models with capability/cost/latency tiers)
- `agents.yaml` — 11 agent role configs with prompts, output schemas, timeouts
- `topology.yaml` — Topology settings (routing, concurrency, quality controls, repair loops)

### Model Configuration (`.env`)

Uses a 4-slot pattern (all OpenAI-compatible):
- `MODEL_SEARCH_*` — search/reader models (low cost, long context)
- `MODEL_ANALYSIS_*` — analysis models (structured extraction)
- `MODEL_REASONING_*` — planning/critique models (strong reasoning)
- `MODEL_WRITING_*` — writing models (strong synthesis)
- Plus `REDIS_*`, `TAVILY_API_KEY`, `ENVIRONMENT`, `LOG_LEVEL`

## Conventions

- All agent prompts are Jinja2 templates in `prompts/{agent}/`, versioned by filename (e.g., `v3_hypothesis.zh.j2`)
- Agent output parsing: `BaseAgent._parse_output()` extracts first JSON object from LLM response
- Frontend agent names must match backend: `planner`, `searcher`, `reader`, `analyzer`, `critic`, `writer`, `validator`, `synthesizer`, `supplementary_search`, `repair_writer_{N}`, `searcher_{id}`, `reader_{id}`, `h_{index}`
- SSE event types: `stage_start`, `stage_complete`, `agent_model_selected`, `agent_thinking`, `agent_output`, `agent_stream_token`, `subtask_complete`, `report_update`, `done`, `cancelled`, `error`
- Claim taxonomy (`app/schemas/agent_outputs.py`): `ClaimType` enum — `factual_claim`, `analytical_claim`, `forecast_claim`, `risk_claim`, `research_limitation`. Every claim must have a type. `research_limitation` claims must not appear in section key_claims.
- Critic resolution routing: `ResolutionAction` enum — `blocker`, `downgrade_required`, `limitations_only`, `acceptable_uncertainties`. Every critic finding must include a `resolution_action`.
- Result payload includes `report`, `claim_graph`, `metrics`, `audit_trail`. Frontend uses `claim_graph` to look up `claim_type` by `claim_id` for rendering.
- `delete_task()` rejects running tasks — must cancel first.
