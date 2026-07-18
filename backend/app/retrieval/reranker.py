"""
Lightweight hybrid reranker.

Pure vector similarity misses exact lexical matches — a query for "SRV-12"
or "IS 2825" should strongly prefer chunks that literally contain that token,
even if some other chunk is a hair closer in embedding space. This reranker
blends the vector score with a lexical signal (term overlap + a strong boost
for exact equipment/standard codes) without needing a second model.

Pure and deterministic, so it's unit-testable in isolation.
"""

import re

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
