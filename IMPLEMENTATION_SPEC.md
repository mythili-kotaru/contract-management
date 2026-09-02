# Vendor Contract & SLA Compliance Assistant — Build Spec

You are implementing a RAG system with a human-in-the-loop (HITL) review step for
answering questions about vendor contracts. Read this whole spec before writing code —
sections reference each other (the risk router depends on the chunking metadata, the
LangSmith harness depends on the eval CSVs, etc.).

## 1. What we're building

A distribution company has vendor contracts (supply agreements, SLAs, distributor
agreements) covering delivery terms, penalty clauses, liability caps, and termination
rights. Users ask natural-language questions; the system answers directly when it's
confident and the question is low-risk, and routes to a human reviewer when it isn't.
Every request is traced in Langfuse; reviewer decisions become a LangSmith eval set used
to regression-test future prompt/chunking changes.

## 2. Tech stack

- **Backend**: Python 3.11+, FastAPI
- **Orchestration**: LangGraph
- **Vector store**: PostgreSQL + pgvector
- **Embeddings**: configurable via `EMBEDDING_MODEL` env var (default `text-embedding-3-small`)
- **LLM**: configurable via `LLM_MODEL` env var — do not hardcode a provider
- **Tracing**: Langfuse Python SDK
- **Evaluation**: LangSmith (`langsmith` Python package)
- **DB migrations**: Alembic (or raw SQL init script — either is fine for a portfolio project)

## 3. Data

Assume a `data/` directory at repo root with this exact structure:

```
data/
  real_contracts_cuad/
    contracts/*.txt                 # 15 real contracts, CC BY 4.0 (CUAD)
    eval_questions_cuad.csv         # columns: contract_file, category, question, ground_truth_answer
  synthetic_vendor_slas/
    contracts/*.txt                 # 6 synthetic vendor SLA contracts
    eval_questions_synthetic.csv    # columns: contract_file, question, ground_truth_answer, category, risk_level
```

Notes on the data:
- Each `.txt` file has a 2-line header (`SOURCE:` and `ORIGINAL TITLE:` or a synthetic
  equivalent) followed by `===` and then the full contract text. Strip the header before
  chunking, but keep it available as document-level metadata (source, title).
- Synthetic contracts are named `NN_vendorslug_agreementtype.txt` (e.g.
  `01_meridian_freight_supply_agreement.txt`) — vendor name can be parsed from the
  filename. CUAD filenames are slugified EDGAR titles — do **not** rely on the filename
  for vendor name; extract the vendor/party names from the contract text itself (look for
  a `Parties` or opening recital section).
- `eval_questions_synthetic.csv` already has a `risk_level` column (`auto`/`hitl`) — use
  this as the labeled ground truth to validate your risk router against before trusting
  it on the CUAD set, which has no `risk_level` column yet.

## 4. Pipeline architecture (LangGraph)

Build one LangGraph graph with these nodes, executed in this order:

```
check_ambiguity
   ├─ ambiguous ──────────────► ask_clarifying_question  [END — returns to user]
   └─ clear ──► retrieve ──► generate ──► assess_risk
                                              ├─ low risk, high confidence ──► auto_answer [END]
                                              └─ high risk OR low confidence ──► queue_for_review [END, async]
```

`queue_for_review` does not resolve in the same request — it writes a row to the review
queue and returns a "pending" response. The reviewer's decision (via the API in section
9) is what ultimately produces the delivered answer.

Every node call must be wrapped in a Langfuse trace/span (see section 8) — implement this
as a decorator or context manager around each node, not as a separate graph node.

## 5. Ingestion & chunking

- Split each contract by numbered section headers (regex on patterns like `^\d+\.\s`,
  `^\d+\.\d+\s`) rather than fixed-size windows — a clause must not be split across two
  chunks.
- Target chunk size: 200–500 tokens. If a single numbered section exceeds ~500 tokens,
  sub-split on sentence boundaries within that section, not arbitrary offsets.
- Store per-chunk metadata: `contract_file`, `vendor_name`, `agreement_type` (supply /
  distributor / logistics / other — infer from title or first line), `section_number`,
  `source` (`cuad` or `synthetic`).

## 6. Vector storage schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE contracts (
    id SERIAL PRIMARY KEY,
    contract_file TEXT UNIQUE NOT NULL,
    vendor_name TEXT,
    agreement_type TEXT,
    source TEXT NOT NULL CHECK (source IN ('cuad', 'synthetic')),
    full_text TEXT NOT NULL
);

CREATE TABLE contract_chunks (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER REFERENCES contracts(id),
    section_number TEXT,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536)  -- match your embedding model's dimension
);

CREATE INDEX ON contract_chunks USING ivfflat (embedding vector_cosine_ops);
```

## 7. Retrieve + generate node

- Retrieve top-k (default k=5) chunks by cosine similarity.
- If the question names a vendor explicitly, filter retrieval to that vendor's chunks
  first; only fall back to unfiltered search if no vendor match exists.
- Generation prompt must instruct the model to answer **only** from the retrieved
  chunks, cite the section number, and explicitly say "not found in the provided
  context" rather than guessing if the chunks don't cover the question.
- Return both the generated answer and the raw top-k similarity scores — the risk node
  needs them.

## 8. Ambiguity check

Flag a question as ambiguous when **both** are true:
1. The question does not name a specific vendor (simple heuristic: no retrieved
   contract's `vendor_name` appears as a substring of the question — refine later with
   an LLM classifier if the heuristic is too noisy).
2. The top-k retrieval spans **3 or more distinct contracts** whose top similarity
   scores are within **0.05** of each other (i.e., no single contract is clearly the
   best match).

When ambiguous, generate a clarifying question listing the candidate vendors found in
the top-k results (e.g. "Which vendor's contract — Meridian, Coastal, or Northstar?").
Do not call the generation node at all in this branch.

## 9. Confidence & risk router

Route to `queue_for_review` if **either** condition holds; otherwise `auto_answer`.

- **Low confidence**: top-1 retrieval similarity score < `0.75` (tune this against the
  eval sets — see section 11).
- **High-risk category**: the question or the matched chunk's clause category falls
  into any of: `Liquidated Damages`, `Cap On Liability`, `Uncapped Liability`,
  `Termination For Cause`, `Insurance`, `Indemnification`, `Minimum Commitment`,
  `Most Favored Nation`, `Exclusivity`. Detect this with a keyword/regex pass over the
  question (penalty, indemnif*, liabilit*, terminat*, insurance, uncapped, exclusiv*,
  minimum commitment, most favored nation) **or** by tagging each chunk with its clause
  category at ingestion time and checking the category of the top retrieved chunk.

Everything else (`Payment Terms`, `Delivery Terms`/lead times, `Warranty Duration`,
`Governing Law`, a plain `Termination For Convenience` notice-period lookup) auto-answers.

## 10. HITL review queue

Data model:

```sql
CREATE TABLE review_queue (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    draft_answer TEXT NOT NULL,
    retrieved_chunks JSONB NOT NULL,
    risk_reason TEXT NOT NULL,       -- why it was routed here
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','edited','rejected')),
    final_answer TEXT,               -- filled in on approve/edit
    reviewer_note TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
```

API endpoints:

| Method | Path | Purpose |
|---|---|---|
| POST | `/questions` | Submit a question; returns either an immediate answer, a clarifying question, or a `pending_review_id` |
| GET | `/review-queue` | List pending items |
| GET | `/review-queue/{id}` | Get one item with full context (question, chunks, draft answer) |
| POST | `/review-queue/{id}/decision` | Body: `{decision: approve\|edit\|reject, final_answer?, note?}` — resolves the item |

Every resolved item (`approved` or `edited`) is a candidate row for the LangSmith
dataset in section 11 — log it to a table or export job, don't let it live only in
`review_queue`.

## 11. Langfuse tracing

- Wrap the whole `/questions` request in one Langfuse trace.
- Create a span per graph node (`check_ambiguity`, `retrieve`, `generate`,
  `assess_risk`, and the terminal branch taken).
- Log on the `retrieve` span: query, top-k scores, which contracts matched.
- Log on the `generate` span: prompt version/id, token counts, cost, latency.
- Log on the trace itself: final branch (`auto_answer` / `queue_for_review` /
  `ask_clarifying_question`) and the risk reason if routed to review.
- Tag traces with a `prompt_version` so you can filter Langfuse by version when you
  start iterating on prompts.

## 12. LangSmith eval harness

- Load `eval_questions_cuad.csv` and `eval_questions_synthetic.csv` as two separate
  LangSmith datasets (`contract-qa-cuad`, `contract-qa-synthetic`).
- Write an evaluator that runs each `question` through the full pipeline (up to
  `generate` — skip the HITL branch for eval runs) and scores the output against
  `ground_truth_answer` using two metrics: (a) an LLM-graded correctness score, and
  (b) whether the cited section number's text actually contains the ground-truth answer
  (a cheap faithfulness check).
- For the synthetic dataset, additionally check whether your risk router's decision
  matches the labeled `risk_level` column — this validates section 9's thresholds before
  you trust them on real contracts.
- Write this as a standalone script (`scripts/run_eval.py`) you can run after any prompt
  or chunking change, and have it print a before/after diff if a previous run's results
  are cached locally.

## 13. Suggested repo structure

```
.
├── app/
│   ├── main.py                # FastAPI app, endpoint definitions
│   ├── graph.py                # LangGraph graph + node implementations
│   ├── ingestion.py            # chunking + embedding + DB load
│   ├── risk_router.py          # section 9 logic
│   ├── db.py                   # pgvector queries
│   └── tracing.py              # Langfuse wrapper/decorator
├── scripts/
│   ├── load_data.py            # one-off: ingest data/ into Postgres
│   └── run_eval.py             # section 12
├── data/                        # provided sample data (section 3)
├── migrations/ or init.sql
└── requirements.txt
```

## 14. Definition of done, per phase

**Phase 1 — ingestion + RAG core**
- [ ] All 21 contracts chunked and loaded into pgvector with correct metadata
- [ ] `/questions` returns a cited answer for a clear, unambiguous, low-risk question
- [ ] Every call produces a visible Langfuse trace with retrieve + generate spans

**Phase 2 — ambiguity + risk routing + HITL**
- [ ] A vendor-unspecified question with 3+ contract matches triggers a clarifying
      question instead of a guessed answer
- [ ] All 27 synthetic eval questions, run through the router, match their labeled
      `risk_level` at least 90% of the time (investigate and fix any mismatch — don't
      just raise the threshold until it passes)
- [ ] `/review-queue` shows pending items with full context; `/review-queue/{id}/decision`
      resolves them and produces a final answer

**Phase 3 — LangSmith eval**
- [ ] Both CSVs load as LangSmith datasets
- [ ] `scripts/run_eval.py` runs end-to-end and prints correctness + faithfulness scores
- [ ] Changing the chunking strategy (e.g. chunk size) and rerunning shows a measurable
      score change — proving the harness actually detects regressions, not just passes
      trivially
