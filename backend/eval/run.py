"""
Evaluation harness runner.

Runs four evaluations against the live Cypher system and prints a scorecard
plus a JSON report under eval/reports/:

  1. Entity-extraction accuracy   (needs the LLM)
  2. Retrieval + answer quality   (needs Qdrant + Neo4j + LLM)
  3. Time-to-answer vs baseline   (RAG pipeline vs naive keyword search)
  4. Compliance gap detection     (needs Neo4j)

Each section degrades gracefully: if a dependency (a database, the model)
isn't available, that section is reported as SKIPPED with the reason, and
the rest still run.

Usage (from backend/):
    python -m eval.run                 # run everything available
    python -m eval.run --entities      # only entity extraction
    python -m eval.run --retrieval     # only retrieval + answer + timing
    python -m eval.run --compliance    # only compliance
    python -m eval.run --selftest      # metric unit checks only (no services)
"""

from __future__ import annotations
import os
import sys
import json
import time
import argparse
from datetime import datetime

from eval import metrics

_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA = os.path.join(_DIR, "datasets")
_REPORTS = os.path.join(_DIR, "reports")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _hr(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def naive_keyword_search(corpus: list[dict], query: str, top_k: int = 5) -> list[str]:
    """Traditional search baseline: rank docs by keyword-overlap count.

    corpus items: {doc_id, file_name, text}. Returns ranked file names.
    """
    q_terms = {w for w in metrics.normalize_name(query).split() if len(w) > 2}
    scored = []
    for doc in corpus:
        text_norm = metrics.normalize_name(doc.get("text", ""))
        score = sum(text_norm.count(t) for t in q_terms)
        if score:
            scored.append((score, doc.get("file_name", doc.get("doc_id", ""))))
    scored.sort(reverse=True)
    return [name for _, name in scored[:top_k]]


# ---------------------------------------------------------------------------
# 1. Entity-extraction accuracy
# ---------------------------------------------------------------------------

def eval_entities() -> dict:
    _hr("1. ENTITY-EXTRACTION ACCURACY (across document types)")
    gold_docs = load_jsonl(os.path.join(_DATA, "entities_gold.jsonl"))

    try:
        from app.ai.entity_extractor import EntityExtractor
        from app.ingestion.canonical_document import CanonicalDocument
        extractor = EntityExtractor()
    except Exception as e:
        print(f"  SKIPPED — could not init extractor/LLM: {e}")
        return {"status": "skipped", "reason": str(e)}

    per_doc = []
    prf_values = {"precision": [], "recall": [], "f1": []}
    for doc in gold_docs:
        cdoc = CanonicalDocument(
            file_path=f"{doc['doc_id']}", file_type=doc.get("file_type", "text"),
            text=doc["text"],
        )
        try:
            cdoc = extractor.process_document(cdoc)
        except Exception as e:
            print(f"  {doc['doc_id']}: extraction failed ({e})")
            continue
        prf = metrics.entity_prf(cdoc.entities, doc["gold_entities"], match_type=False)
        per_doc.append({"doc_id": doc["doc_id"], **prf})
        for k in prf_values:
            prf_values[k].append(prf[k])
        print(f"  {doc['doc_id']:<20} P={prf['precision']:.2f} "
              f"R={prf['recall']:.2f} F1={prf['f1']:.2f} "
              f"(tp={prf['tp']} fp={prf['fp']} fn={prf['fn']})")

    summary = {k: metrics.aggregate(v) for k, v in prf_values.items()}
    print(f"\n  MACRO  precision={summary['precision']:.3f}  "
          f"recall={summary['recall']:.3f}  f1={summary['f1']:.3f}")
    return {"status": "ok", "macro": summary, "per_doc": per_doc}


# ---------------------------------------------------------------------------
# 2 + 3. Retrieval, answer quality, time-to-answer
# ---------------------------------------------------------------------------

def eval_retrieval_and_timing() -> dict:
    _hr("2. RETRIEVAL + ANSWER QUALITY   3. TIME-TO-ANSWER vs BASELINE")
    questions = load_jsonl(os.path.join(_DATA, "qa_benchmark.jsonl"))
    gold_docs = load_jsonl(os.path.join(_DATA, "entities_gold.jsonl"))

    # Corpus for the naive baseline (reconstructed from the gold docs).
    corpus = [{
        "doc_id": d["doc_id"],
        "file_name": (d["expected_file"] if "expected_file" in d
                      else _guess_name(d)),
        "text": d["text"],
    } for d in gold_docs]

    try:
        from app.retrieval.query_engine import QueryEngine
        engine = QueryEngine()
    except Exception as e:
        print(f"  SKIPPED — could not init QueryEngine (DBs/LLM down?): {e}")
        return {"status": "skipped", "reason": str(e)}

    hits, rr, coverage, citations = [], [], [], []
    rag_times, baseline_times = [], []
    per_q = []

    for q in questions:
        expected = q["expected_files"]

        # --- Baseline: naive keyword search (traditional search) ---
        t0 = time.perf_counter()
        base_hits = naive_keyword_search(corpus, q["question"])
        baseline_times.append(time.perf_counter() - t0)
        base_hit = metrics.retrieval_hit(base_hits, expected, k=3)

        # --- Full RAG pipeline ---
        t0 = time.perf_counter()
        try:
            result = engine.query(q["question"])
        except Exception as e:
            print(f"  Q: {q['question'][:50]}... ERROR: {e}")
            continue
        rag_times.append(time.perf_counter() - t0)

        retrieved = [s.get("file_path", "") for s in result.get("sources", [])]
        answer = result.get("answer", "")

        hit = metrics.retrieval_hit(retrieved, expected, k=5)
        mrr = metrics.reciprocal_rank(retrieved, expected)
        cov = metrics.answer_coverage(answer, q.get("must_include", []))
        cite = metrics.citation_present(answer, expected)

        hits.append(1.0 if hit else 0.0)
        rr.append(mrr)
        coverage.append(cov)
        citations.append(1.0 if cite else 0.0)
        conf = result.get("confidence", {})
        per_q.append({
            "question": q["question"], "hit": hit, "mrr": round(mrr, 2),
            "coverage": cov, "cited": cite,
            "confidence": conf.get("label"), "baseline_hit": base_hit,
        })
        print(f"  Q: {q['question'][:52]:<52} hit={_yn(hit)} "
              f"cov={cov:.2f} cite={_yn(cite)} conf={conf.get('label','-')}")

    summary = {
        "retrieval_hit_rate@5": metrics.aggregate(hits),
        "mrr": metrics.aggregate(rr),
        "answer_coverage": metrics.aggregate(coverage),
        "citation_rate": metrics.aggregate(citations),
        "rag_latency": metrics.latency_stats(rag_times),
        "baseline_latency": metrics.latency_stats(baseline_times),
    }
    print(f"\n  Retrieval hit-rate@5 : {summary['retrieval_hit_rate@5']:.3f}")
    print(f"  Mean reciprocal rank : {summary['mrr']:.3f}")
    print(f"  Answer key-point cov : {summary['answer_coverage']:.3f}")
    print(f"  Citation rate        : {summary['citation_rate']:.3f}")
    print(f"  Time-to-answer (RAG) : mean {summary['rag_latency']['mean']}s "
          f"p95 {summary['rag_latency']['p95']}s")
    print(f"  Baseline keyword sch : mean {summary['baseline_latency']['mean']}s "
          f"(no synthesized/cited answer — raw file hits only)")
    return {"status": "ok", "summary": summary, "per_question": per_q}


def _guess_name(doc: dict) -> str:
    ext = {"pdf": ".pdf", "email": ".eml", "text": ".txt"}.get(doc.get("file_type"), ".txt")
    return doc["doc_id"] + ext


def _yn(b): return "Y" if b else "n"


# ---------------------------------------------------------------------------
# 4. Compliance gap-detection accuracy
# ---------------------------------------------------------------------------

def eval_compliance() -> dict:
    _hr("4. COMPLIANCE GAP-DETECTION ACCURACY")
    gold = {r["regulation"]: r["gold_status"]
            for r in load_jsonl(os.path.join(_DATA, "compliance_gold.jsonl"))}

    try:
        from app.storage.neo4j import Neo4jStorage
        from app.retrieval.compliance import ComplianceAnalyzer
        from app.config import Neo4jConfig
        neo = Neo4jStorage(uri=Neo4jConfig.URI, user=Neo4jConfig.USER,
                           password=Neo4jConfig.PASSWORD, database=Neo4jConfig.DATABASE)
        report = ComplianceAnalyzer(neo).analyze(use_llm=False)
    except Exception as e:
        print(f"  SKIPPED — could not run compliance analysis (Neo4j down?): {e}")
        return {"status": "skipped", "reason": str(e)}

    pred = {r["name"]: r["status"] for r in report.get("regulations", [])}
    if not pred:
        print("  No REGULATION entities in the graph yet — ingest regulatory "
              "documents first, then re-run.")
        return {"status": "empty", "predicted": {}}

    acc = metrics.classification_accuracy(pred, gold)
    for reg, gold_status in gold.items():
        p = pred.get(reg, "—(not found)")
        mark = "OK " if p == gold_status else "XX "
        print(f"  {mark} {reg:<16} gold={gold_status:<8} predicted={p}")
    print(f"\n  Classification accuracy: {acc['accuracy']:.3f} "
          f"({acc['correct']}/{acc['n']} matched regulations)")
    return {"status": "ok", "accuracy": acc, "predicted": pred}


# ---------------------------------------------------------------------------
# Metric self-test (no services required)
# ---------------------------------------------------------------------------

def selftest() -> bool:
    _hr("METRIC SELF-TEST (no services)")
    ok = True

    prf = metrics.entity_prf(
        [{"name": "Pump P-101", "type": "EQUIPMENT"}, {"name": "bearing", "type": "COMPONENT"}],
        [{"name": "pump p101", "type": "EQUIPMENT"}, {"name": "seal", "type": "COMPONENT"}],
        match_type=False)
    ok &= prf["tp"] == 1 and prf["fp"] == 1 and prf["fn"] == 1
    ok &= abs(prf["precision"] - 0.5) < 1e-6 and abs(prf["recall"] - 0.5) < 1e-6

    ok &= metrics.retrieval_hit(["a/b/maint_log_p101.txt"], ["maint_log_p101.txt"], k=5) is True
    ok &= metrics.retrieval_hit(["other.pdf"], ["maint_log_p101.txt"], k=5) is False
    ok &= abs(metrics.reciprocal_rank(["x.pdf", "maint_log_p101.txt"], ["maint_log_p101.txt"]) - 0.5) < 1e-6

    ok &= abs(metrics.answer_coverage("bearing vibration on P-101", ["vibration", "bearing", "P-101"]) - 1.0) < 1e-6
    ok &= metrics.citation_present("see [maint_log_p101.txt] for detail", ["maint_log_p101.txt"]) is True
    ok &= metrics.citation_present("no citation here", ["maint_log_p101.txt"]) is False

    acc = metrics.classification_accuracy({"A": "gap", "B": "covered"}, {"A": "gap", "B": "partial"})
    ok &= acc["accuracy"] == 0.5

    lat = metrics.latency_stats([1.0, 2.0, 3.0, 4.0])
    ok &= lat["p50"] == 2.5 and lat["max"] == 4.0

    print("  All metric self-tests PASSED" if ok else "  METRIC SELF-TESTS FAILED")
    return ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Cypher evaluation harness")
    ap.add_argument("--entities", action="store_true", help="entity extraction only")
    ap.add_argument("--retrieval", action="store_true", help="retrieval+answer+timing only")
    ap.add_argument("--compliance", action="store_true", help="compliance only")
    ap.add_argument("--selftest", action="store_true", help="metric self-test only")
    args = ap.parse_args()

    run_all = not (args.entities or args.retrieval or args.compliance or args.selftest)
    report = {"timestamp": datetime.now().isoformat(), "sections": {}}

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    # Always self-test metrics first so a metric regression is caught early.
    selftest()

    if run_all or args.entities:
        report["sections"]["entities"] = eval_entities()
    if run_all or args.retrieval:
        report["sections"]["retrieval"] = eval_retrieval_and_timing()
    if run_all or args.compliance:
        report["sections"]["compliance"] = eval_compliance()

    os.makedirs(_REPORTS, exist_ok=True)
    out = os.path.join(_REPORTS, f"report_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    _hr("REPORT SAVED")
    print(f"  {out}")


if __name__ == "__main__":
    main()
