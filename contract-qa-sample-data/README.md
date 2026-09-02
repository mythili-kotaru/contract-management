# Contract QA + HITL starter dataset

Two complementary sets, built to plug straight into the RAG + HITL pipeline (ingestion → retrieve/generate → confidence & risk router → auto-answer / human review queue → LangSmith eval set).

## 1. `real_contracts_cuad/` — real contracts, messy legal English

15 supply and distributor agreements filtered from **CUAD** (Contract Understanding Atticus Dataset) — 510 real commercial contracts sourced from SEC EDGAR filings, expert-labeled by legal professionals across 41 clause categories.

- **Source:** Hendrycks, Burns, Chen, Ball. "CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review." arXiv:2103.06268 (2021). https://www.atticusprojectai.org/cuad
- **License:** CC BY 4.0 — keep attribution to The Atticus Project if you publish anything built from it.
- **`contracts/`**: full text of each contract (real, occasionally messy formatting — good for stress-testing chunking).
- **`eval_questions_cuad.csv`**: 117 question/answer pairs pulled from CUAD's own expert labels, filtered to the 17 categories most relevant to vendor-contract risk review (Termination For Convenience, Cap On Liability, Uncapped Liability, Liquidated Damages, Warranty Duration, Insurance, Exclusivity, Most Favored Nation, Minimum Commitment, Volume Restriction, Price Restrictions, Audit Rights, Governing Law, Change Of Control, Anti-Assignment, Renewal Term, Notice Period To Terminate Renewal). No `risk_level` column yet — that's a good first exercise: apply your router's rules to these 117 rows yourself.

Use this set to prove your retrieval and chunking hold up on real, inconsistently formatted contract text.

## 2. `synthetic_vendor_slas/` — clean, scenario-matched, fully controlled

6 fictional vendor contracts (Northgate Distribution Co. as buyer, 6 different vendors) written specifically to match the delivery-SLA / penalty / termination-for-cause scenario — the flavor CUAD doesn't really have.

- **`contracts/`**: deliberately varied —
  - `01_meridian_freight` — clean tiered penalty schedule (easy retrieval case)
  - `02_coastal_components` — **ambiguous penalty language on purpose** ("a portion of payment reasonably related to...") — use this to test that your router correctly flags low-confidence answers instead of confidently inventing a percentage
  - `03_prairie_fabricators` — low-risk, mostly-auto-answerable contract
  - `04_northstar_coldchain` — strict SLA with steep liquidated damages and fast termination
  - `05_globalcircuit` — indemnification + uncapped liability carve-outs
  - `06_redwood_distribution` — exclusivity, MFN, minimum commitment
- **`eval_questions_synthetic.csv`**: 27 Q&A pairs, each with a `risk_level` column (`auto` or `hitl`) already assigned — a ready-made starting ruleset for your confidence/risk router (13 auto, 14 hitl) and a seed LangSmith dataset with ground truth you can trust completely, since you know exactly what's in these contracts.

## Suggested use by phase

- **Phase 1 (ingestion + RAG + Langfuse):** ingest both sets, trace every retrieval/generation call.
- **Phase 2 (router + HITL queue):** build your rules against the synthetic set's `risk_level` labels first — they're clean ground truth. Then run the same rules against the CUAD questions and see where they disagree with what a lawyer would actually flag.
- **Phase 3 (LangSmith eval):** load both CSVs as datasets; the synthetic one tests scenario accuracy, the CUAD one tests robustness against real contract language.
