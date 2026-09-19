# Scalable Agentic System for Intelligent Tool Selection and Execution

A working prototype of a hierarchical tool-retrieval architecture that lets
an LLM agent operate over a large (10 to 1000+) tool catalog without ever
seeing more than a handful of tools at once - built around a PayPal-like
API surface (invoices, payments, customers, subscriptions, disputes,
reports, payouts) plus a RAG knowledge-search tool and a system-introspection
tool.

**Runs fully with no API key.** `LLM_PROVIDER=mock` (the default) uses a
deterministic, rule-based planner instead of a real LLM call, so the whole
demo - chat, retrieval, ranking, execution against a stateful mock API - works
offline and for free. Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and flip
`LLM_PROVIDER` to route the same retrieved-tool-subset through a real model.

```
USER
 -> Domain Router          (which part of the system?)
 -> Semantic Retriever     (which tools, by meaning?)
 -> Ranker                 (best few, using 5 weighted signals)
 -> Relevant Tool Subset   (this is ALL the planner ever sees)
 -> LLM Planner            (or deterministic mock, if no API key)
 -> Parameter Validator    (never hallucinate a missing value)
 -> Execution Engine       (retries, backoff, output-chaining)
 -> Result Validator
 -> Natural Language Response
```

See `docs/architecture.md` for full Mermaid diagrams, `docs/design-decisions.md`
for the "why X over Y" justification, and `docs/evaluation.md` for measured
accuracy/latency/scalability results.

## What's actually real vs. simulated

- **Real**: the entire pipeline (routing, retrieval, ranking, planning,
  validation, execution, RAG, system search), a stateful mock PayPal API
  (FastAPI + SQLite - data persists across calls), SQLite-backed execution
  history/state, a live web dashboard.
- **Simulated (by design)**: the "PayPal API" is a local mock, not the real
  PayPal API - per the assignment, no real credentials are required or used.
- **~38 hand-authored tools are fully executable** end-to-end (this is what
  the chat demo actually uses); the remaining tools in a scaled-up registry
  (e.g. 500 or 1000) are auto-generated for benchmarking retrieval/ranking
  latency at scale (`scripts/generate_tools.py`) and are not wired to real
  endpoints - hand-writing 1000 endpoints wasn't the point of the exercise.

## Quick start

### 1. Backend

**Linux / macOS**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scripts/generate_tools.py --count 100      # builds data/tools.json
uvicorn app.main:app --reload --port 8000
```

**Windows**
```bat
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python scripts\generate_tools.py --count 100
uvicorn app.main:app --reload --port 8000
```

The API is now live at `http://localhost:8000` (interactive docs at
`http://localhost:8000/docs`, which also shows the mock PayPal endpoints).

### 2. Frontend

The frontend is a single self-contained `frontend/index.html` - no build
step, no npm install.

```bash
cd frontend
python3 -m http.server 5173
```
Then open `http://localhost:5173` in a browser (backend must be running on
port 8000; CORS is already configured).

### 3. Try it

Open the Chat tab and try (or click) any of these:
- "Send an invoice for $50"
- "What was my total sales volume last month?"
- "Is there a dispute open for user_123?"
- "Refund payment PAY-SEED1" (this is HIGH risk - you'll be asked to confirm)
- "How do PayPal disputes work?" (routes to the RAG tool)
- "What tools are available for managing invoices?" (routes to system search)

Watch the right-hand panels: **Tool Funnel** shows how many of the total
registered tools were actually shown to the planner; **Retrieved Tool
Subset**, **Execution Plan**, and **Execution Trace** show every stage of
the pipeline for that request.

Switch to the **Tool Registry** tab to browse/search/filter every
registered tool, the **Scalability** tab to see the 10->1000 tool benchmark,
and **RAG & System Search** to query the knowledge base or the agent's own
system metadata directly.

## Configure an LLM provider (optional)

```bash
cp backend/.env.example backend/.env
# edit backend/.env:
#   LLM_PROVIDER=anthropic
#   ANTHROPIC_API_KEY=sk-ant-...
```
Restart the backend. The planner now sends the same retrieved tool subset
to a real Claude/GPT call instead of the deterministic mock, using the
exact prompt in `app/planner/planner.py`.

## Scale the registry

```bash
cd backend
python scripts/generate_tools.py --count 500     # or 1000
curl -X POST http://localhost:8000/api/admin/reload-registry
```
The running server picks up the new registry size (and rebuilds its
indexes) without a restart. Refresh the dashboard's Tool Registry tab to
see all 500/1000 tools; the Chat tab's Tool Funnel will now show e.g.
"Retrieved: 5 / 500".

## Run the evaluation and benchmark scripts

```bash
cd backend
python scripts/evaluate.py --json data/evaluation_report.json
python scripts/benchmark.py --sizes 10 50 100 500 1000 --json data/benchmark_results.json
cp data/benchmark_results.json ../frontend/benchmark_results.json   # so the dashboard picks it up
```

## Run tests

```bash
cd backend
pytest -q
```

## Project structure

```
scalable-agent/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI entrypoint
│   │   ├── config.py              # all tunable knobs (env-driven)
│   │   ├── domain_router.py
│   │   ├── mock_paypal.py         # stateful mock PayPal API (FastAPI + SQLite)
│   │   ├── agents/orchestrator.py # wires the full pipeline together
│   │   ├── registry/              # tool schema, core tools, registry store
│   │   ├── retrieval/             # TF-IDF semantic retriever
│   │   ├── ranking/                # weighted multi-signal ranker
│   │   ├── planner/                # LLM provider abstraction, mock planner, planner
│   │   ├── validation/             # parameter validator
│   │   ├── executor/                # execution engine (retries/backoff/chaining)
│   │   ├── rag/                     # RAG engine + knowledge base
│   │   ├── system_search/           # meta/introspection tool
│   │   ├── memory/                  # SQLite state store
│   │   ├── observability/           # structured logging + tracer
│   │   ├── api/routes.py            # public API surface
│   │   └── data/
│   │       ├── tools.json           # generated registry (gitignored-in-spirit; regenerate)
│   │       └── knowledge/*.md       # sample RAG documents
│   ├── scripts/
│   │   ├── generate_tools.py        # scale the registry to N tools
│   │   ├── evaluate.py              # accuracy/latency eval + baseline comparison
│   │   └── benchmark.py             # 10->1000 tool scalability benchmark
│   ├── tests/
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   └── index.html                   # single-file dashboard (no build step)
├── docs/
│   ├── architecture.md              # Mermaid diagrams + component reference
│   ├── api.md
│   ├── evaluation.md
│   └── design-decisions.md
└── docker-compose.yml
```

## Docker

```bash
docker compose up --build
```
Backend on `:8000`, frontend on `:5173`.
