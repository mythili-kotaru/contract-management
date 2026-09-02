# Vendor Contract & SLA Compliance Assistant

A RAG system with Human-in-the-Loop (HITL) review and evaluation harnessing for querying vendor contracts and service level agreements (SLAs).

## Features

- **Agentic RAG with LangGraph**: Multi-step graph architecture with query ambiguity detection, document retrieval, and risk assessment.
- **Ambiguity Detection**: Flags vendor-unspecified questions spanning multiple candidate contracts and prompts clarifying questions.
- **Risk Router & Human-in-the-Loop (HITL)**: Automatically routes high-risk clauses (Liquidated Damages, Liability Caps, Termination for Cause, Indemnification, etc.) or low-confidence queries (< 0.70 similarity) to a dedicated human review queue.
- **FastAPI Endpoints**: Full REST interface for asking questions, retrieving review queue items, and recording human reviewer decisions (`approve`, `edit`, `reject`).
- **PostgreSQL + pgvector**: 3072-dimensional vector store optimized for `models/gemini-embedding-2`.
- **Evaluation Harness (LangSmith)**: Benchmark suite for automated correctness, faithfulness, and risk routing match metrics.

---

## Evaluation Results

| Metric | Synthetic Dataset | CUAD Dataset |
| :--- | :---: | :---: |
| **Average Correctness** | **94%** | **67%** |
| **Average Faithfulness** | **100%** | **60%** |
| **Risk Router Match Accuracy** | **100%** (27/27) | *N/A* |

---

## Getting Started

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Google Gemini API Key

### 2. Environment Setup
Create a `.env` file from the template:
```bash
cp .env.template .env
```
Fill in your API keys in `.env`:
- `GOOGLE_API_KEY`: Your Google Gemini API Key
- `LANGSMITH_API_KEY`: (Optional) LangSmith API Key for evaluations
- `LANGFUSE_PUBLIC_KEY` & `LANGFUSE_SECRET_KEY`: (Optional) Langfuse tracing keys

### 3. Start PostgreSQL Vector Database
```bash
docker compose up -d
```

### 4. Ingest Contracts
```bash
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=. python scripts/load_data.py
```

### 5. Run API Server
```bash
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=. uvicorn app.main:app --reload
```
Interactive Swagger docs are available at `http://127.0.0.1:8000/docs`.

### 6. Run Evaluations
```bash
PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python PYTHONPATH=. python scripts/run_eval.py
```

---

## Project Structure

```
├── app/
│   ├── db.py            # SQLAlchemy models, pgvector tables, and similarity search
│   ├── graph.py         # LangGraph graph and node definitions
│   ├── ingestion.py     # Document parsing, section chunking, and embedding
│   ├── main.py          # FastAPI application & REST endpoints
│   ├── risk_router.py   # Confidence and keyword-based risk routing logic
│   └── tracing.py       # Langfuse tracing helpers
├── contract-qa-sample-data/
│   ├── real_contracts_cuad/     # 15 CUAD contracts + evaluation dataset
│   └── synthetic_vendor_slas/   # 6 synthetic SLA contracts + evaluation dataset
├── scripts/
│   ├── load_data.py     # Database initialization and ingestion script
│   └── run_eval.py      # LangSmith automated evaluation harness
├── docker-compose.yml   # PostgreSQL + pgvector container
└── pyproject.toml       # Python package configuration & dependencies
```
