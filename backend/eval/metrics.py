"""
Pure, dependency-free metric functions for the evaluation harness.

Keeping these pure (no DB/LLM/network) means they are fast, deterministic,
and unit-testable in isolation — the runner feeds them real system output.
"""

from __future__ import annotations
import re
import statistics


# ---------------------------------------------------------------------------
# Shared normalization (mirrors EntityExtractor so eval matches production)
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalize an entity/file name for tolerant matching."""
    if not name:
        return ""
    s = str(name).strip().lower()
    s = re.sub(r'\b([a-z]{1,4})[\s\-_]*(\d{1,5})\b', r'\1\2', s)  # tag numbers
    s = re.sub(r'[^a-z0-9\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _base(path: str) -> str:
    return re.split(r'[\\/]', str(path or ""))[-1].lower()


# ---------------------------------------------------------------------------
# Entity-extraction accuracy
# ---------------------------------------------------------------------------

def entity_prf(predicted: list[dict], gold: list[dict],
               match_type: bool = True) -> dict:
    """Precision / recall / F1 of extracted entities against a gold set.

    An entity matches if its normalized name (and, when match_type, its
    UPPER type) is present in the gold set. Returns counts plus p/r/f1.
    """
    def key(e):
        k = normalize_name(e.get("name", ""))
        return (k, (e.get("type", "") or "").upper()) if match_type else (k,)

    pred_keys = {key(e) for e in predicted if normalize_name(e.get("name", ""))}
    gold_keys = {key(e) for e in gold if normalize_name(e.get("name", ""))}

    tp = len(pred_keys & gold_keys)
    fp = len(pred_keys - gold_keys)
    fn = len(gold_keys - pred_keys)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3),
            "missed": sorted(k[0] for k in (gold_keys - pred_keys))}


# ---------------------------------------------------------------------------
# Retrieval quality
# ---------------------------------------------------------------------------

def retrieval_hit(retrieved_paths: list[str], expected_files: list[str],
                  k: int | None = None) -> bool:
    """True if any expected file name appears in the top-k retrieved paths."""
    paths = retrieved_paths[:k] if k else retrieved_paths
    got = {_base(p) for p in paths}
    want = {_base(f) for f in expected_files}
    return bool(got & want) if want else True


def reciprocal_rank(retrieved_paths: list[str], expected_files: list[str]) -> float:
    """Mean-reciprocal-rank contribution: 1/rank of the first expected hit."""
    want = {_base(f) for f in expected_files}
    for i, p in enumerate(retrieved_paths, 1):
        if _base(p) in want:
            return 1.0 / i
    return 0.0


# ---------------------------------------------------------------------------
# Answer quality
# ---------------------------------------------------------------------------

def answer_coverage(answer: str, must_include: list[str]) -> float:
    """Fraction of expected key points/keywords present in the answer."""
    if not must_include:
        return 1.0
    a = (answer or "").lower()
    hits = sum(1 for kw in must_include if kw.lower() in a)
    return round(hits / len(must_include), 3)


def citation_present(answer: str, expected_files: list[str]) -> bool:
    """True if the answer cites at least one expected source file by name."""
    a = (answer or "").lower()
    for f in expected_files:
        base = _base(f)
        stem = re.sub(r'\.[a-z0-9]+$', '', base)
        if base in a or (len(stem) > 3 and stem in a):
            return True
    return False


# ---------------------------------------------------------------------------
# Compliance gap-detection accuracy
# ---------------------------------------------------------------------------

def classification_accuracy(pred: dict[str, str], gold: dict[str, str]) -> dict:
    """Accuracy of predicted status labels (covered/partial/gap) vs gold,
    keyed by regulation name."""
    keys = [k for k in gold if k in pred]
    if not keys:
        return {"n": 0, "accuracy": 0.0, "correct": 0}
    correct = sum(1 for k in keys if pred[k] == gold[k])
    return {"n": len(keys), "correct": correct,
            "accuracy": round(correct / len(keys), 3)}


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def latency_stats(times_s: list[float]) -> dict:
    """Summary statistics for a list of latencies (seconds)."""
    if not times_s:
        return {"n": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0,
                "min": 0.0, "max": 0.0}
    s = sorted(times_s)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return {
        "n": len(s),
        "mean": round(statistics.mean(s), 3),
        "p50": round(statistics.median(s), 3),
        "p95": round(p95, 3),
        "min": round(s[0], 3),
        "max": round(s[-1], 3),
    }


def aggregate(values: list[float]) -> float:
    """Mean of a list, 0.0 if empty (used to average per-question scores)."""
    return round(statistics.mean(values), 3) if values else 0.0
