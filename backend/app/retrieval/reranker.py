"""
Lightweight hybrid reranker.

Pure vector similarity misses exact lexical matches — a query for "SRV-12"
or "IS 2825" should strongly prefer chunks that literally contain that token,
even if some other chunk is a hair closer in embedding space. This reranker
blends the vector score with a lexical signal (term overlap + a strong boost
for exact equipment/standard codes) without needing a second model.

Pure and deterministic, so it's unit-testable in isolation.
"""

import math
import os
import re
import threading

# Ignore any *stored* HuggingFace token when fetching models. A stale token in
# ~/.cache/huggingface/token fails signature verification and blocks downloads
# of even public models like the reranker. This must be set before
# huggingface_hub is imported (it reads the flag into a constant at import), so
# it lives at module top, ahead of the lazy sentence_transformers import below.
# An explicit HF_TOKEN env var still works (for gated models), and users can
# override by exporting HF_HUB_DISABLE_IMPLICIT_TOKEN=0.
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")

# Equipment tags / standard codes: letters + digits, e.g. P-101, SRV-12, IS2825.
_CODE_RE = re.compile(r'\b[A-Za-z]{1,4}[-_]?\d{1,5}\b')
_WORD_RE = re.compile(r'\b\w{3,}\b')

_STOPWORDS = {
    "what", "how", "why", "when", "where", "which", "the", "are", "was", "were",
    "has", "have", "had", "does", "did", "and", "for", "with", "from", "about",
    "this", "that", "these", "those", "list", "show", "tell", "give", "all",
    "any", "does", "used", "into", "over",
}


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "")}


def _codes(text: str) -> set[str]:
    return {c.lower().replace("-", "").replace("_", "") for c in _CODE_RE.findall(text or "")}


def lexical_score(query: str, text: str) -> float:
    """0..1 lexical relevance of `text` to `query`.

    Combines fraction of query keywords present with a strong bonus when an
    exact tag/standard code from the query appears in the text.
    """
    q_words = {w for w in _tokens(query) if w not in _STOPWORDS}
    if not q_words:
        return 0.0
    t_words = _tokens(text)
    overlap = len(q_words & t_words) / len(q_words)

    q_codes = _codes(query)
    code_hit = 1.0 if (q_codes and q_codes & _codes(text)) else 0.0

    # Weight exact codes heavily — they're the highest-precision signal.
    return min(1.0, 0.6 * overlap + 0.4 * code_hit)


class CrossEncoderReranker:
    """Lazy, process-wide cross-encoder that scores (query, passage) pairs.

    Loaded once on CPU (keeps the GPU free for the LLM), offline-first like the
    embedding model. If it can't be loaded (not cached + offline, missing dep),
    `available` stays False and callers fall back to the lexical reranker.
    """

    _model = None
    _model_name = None
    _tried = False           # we attempt the load at most once per process
    _lock = threading.Lock()

    def __init__(self, model_name: str):
        self.model_name = model_name

    @staticmethod
    def _load(model_name: str):
        from sentence_transformers import CrossEncoder
        # Offline-first: use the local cache with no HTTP round-trip.
        try:
            return CrossEncoder(model_name, device="cpu", local_files_only=True)
        except TypeError:
            return CrossEncoder(model_name, device="cpu")  # older ST signature
        except Exception:
            # Not cached — download it (first run only).
            print("  Not in local cache — downloading from HuggingFace (first run only)...")
            return CrossEncoder(model_name, device="cpu")

    def _get_model(self):
        cls = type(self)
        with cls._lock:
            if cls._tried:
                return cls._model
            cls._tried = True
            try:
                print(f"Loading cross-encoder reranker '{self.model_name}' (CPU)...")
                cls._model = self._load(self.model_name)
                cls._model_name = self.model_name
                print("  Cross-encoder ready.")
            except Exception as e:
                print(f"  Cross-encoder unavailable ({e}) — falling back to lexical rerank.")
                cls._model = None
            return cls._model

    @property
    def available(self) -> bool:
        return self._get_model() is not None

    def scores(self, query: str, texts: list[str]) -> list[float]:
        model = self._get_model()
        if model is None:
            return []
        raw = model.predict([(query, t) for t in texts])
        # Squash logits to 0..1 so they combine cleanly with the code bonus.
        return [1.0 / (1.0 + math.exp(-float(s))) for s in raw]


_cross_encoder: CrossEncoderReranker | None = None


def get_cross_encoder(model_name: str) -> CrossEncoderReranker:
    global _cross_encoder
    if _cross_encoder is None or _cross_encoder.model_name != model_name:
        _cross_encoder = CrossEncoderReranker(model_name)
    return _cross_encoder


def rerank_cross_encoder(query: str, chunks: list[dict], top_k: int,
                         model_name: str, code_bonus: float = 0.15) -> list[dict] | None:
    """Rerank with a cross-encoder, keeping a bonus for exact tag/code matches.

    Returns None (so the caller can fall back to lexical) if the model isn't
    available; otherwise returns the top_k chunks with a `rerank_score`.
    """
    if not chunks:
        return []
    ce = get_cross_encoder(model_name)
    if not ce.available:
        return None

    texts = [c.get("text", "") for c in chunks]
    sims = ce.scores(query, texts)
    if not sims:
        return None

    q_codes = _codes(query)
    ranked = []
    for c, sim in zip(chunks, sims):
        code_hit = 1.0 if (q_codes and q_codes & _codes(c.get("text", ""))) else 0.0
        combined = sim + code_bonus * code_hit
        ranked.append((combined, sim, c))

    ranked.sort(key=lambda t: t[0], reverse=True)
    out = []
    for combined, sim, c in ranked[:top_k]:
        c = dict(c)
        c["rerank_score"] = round(combined, 4)
        c["ce_score"] = round(sim, 4)
        out.append(c)
    return out


def rerank(query: str, chunks: list[dict], top_k: int, alpha: float = 0.35) -> list[dict]:
    """Reorder `chunks` by (vector score + alpha * lexical score); return top_k.

    Each chunk keeps its original vector `score`; a `rerank_score` is added for
    transparency/debugging. Stable for ties on the vector score.
    """
    if not chunks:
        return []
    ranked = []
    for c in chunks:
        lex = lexical_score(query, c.get("text", ""))
        combined = c.get("score", 0.0) + alpha * lex
        ranked.append((combined, lex, c))

    ranked.sort(key=lambda t: t[0], reverse=True)
    out = []
    for combined, lex, c in ranked[:top_k]:
        c = dict(c)
        c["rerank_score"] = round(combined, 4)
        c["lexical_score"] = round(lex, 4)
        out.append(c)
    return out
