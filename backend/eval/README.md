# Cypher Evaluation Harness

Measures the system against the problem statement's **Evaluation Focus**:
entity-extraction accuracy, query answer quality, knowledge-graph linkage,
time-to-answer vs. traditional search, and compliance gap-detection accuracy.

## Running

From the `backend/` directory:

```bash
python -m eval.run              # run every section that its services allow
python -m eval.run --entities   # entity-extraction accuracy only (needs LLM)
python -m eval.run --retrieval  # retrieval + answer + timing (needs Qdrant+Neo4j+LLM)
python -m eval.run --compliance # compliance gap detection (needs Neo4j)
python -m eval.run --selftest   # metric unit checks only, no services needed
```

Each section **degrades gracefully**: if a database or the model isn't
available it's reported as `SKIPPED` with the reason, and the others still run.
A JSON report is written to `eval/reports/report_<timestamp>.json`.

## What each section measures

| Section | Metric | Needs |
|---|---|---|
| 1. Entity extraction | precision / recall / F1 vs. hand-labeled entities, per document type | LLM |
| 2. Retrieval + answer | hit-rate@5, MRR, answer key-point coverage, citation rate | Qdrant + Neo4j + LLM |
| 3. Time-to-answer | RAG pipeline latency (mean/p50/p95) vs. a naive keyword-search baseline | same as #2 |
| 4. Compliance | classification accuracy of covered / partial / gap vs. gold labels | Neo4j |

## Datasets (`eval/datasets/`)

- `entities_gold.jsonl` — documents (text/pdf/email) with hand-labeled gold entities.
- `qa_benchmark.jsonl` — benchmark questions with expected source files and must-include key points.
- `compliance_gold.jsonl` — expected coverage status per regulation.

Extend these with real industrial document samples to make the numbers
representative of your own corpus. For the retrieval and compliance sections
to score above zero, the referenced documents must first be **ingested** into
the running system (they share the same file names used in the datasets).

## Interpreting time-to-answer

The naive keyword baseline is near-instant but returns only raw file hits.
The RAG pipeline is slower because it embeds the query, retrieves, traverses
the graph, and synthesizes a **cited** answer — the coverage and citation
metrics quantify that added value against the extra latency.
