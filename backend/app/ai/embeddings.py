"""
Embedding model wrapper — local sentence-transformers.

Uses a small, fast embedding model (all-MiniLM-L6-v2, 384-dim) that runs
locally on CPU. No API calls needed — works on free-tier AWS accounts
where Bedrock model invocation is restricted.

The public API (embed_batch / embed_query) is unchanged, so the
ingestion pipeline and vector retriever work without modification.
"""

from sentence_transformers import SentenceTransformer

from app.config import BedrockConfig, QdrantConfig


class BGEWrapper:
    """Local sentence-transformers embedding wrapper.

    Named BGEWrapper for backward compatibility — the rest of the
    codebase imports this name.
    """

    _model = None  # Class-level singleton to avoid reloading

    def __init__(self, model_name: str = None):
        self.model_name = model_name or BedrockConfig.LOCAL_EMBED_MODEL
        if BGEWrapper._model is None:
            print(f"[Embeddings] Loading local model: {self.model_name}")
            BGEWrapper._model = SentenceTransformer(self.model_name)
            print(f"[Embeddings] Model loaded — {QdrantConfig.VECTOR_SIZE}-dim vectors")

    @property
    def model(self):
        return BGEWrapper._model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document chunks. Returns a list of vectors."""
        if not texts:
            return []
        # Truncate very long texts (model max is ~256 tokens / ~1500 chars)
        truncated = [t[:2000] for t in texts]
        embeddings = self.model.encode(truncated, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for semantic search."""
        embedding = self.model.encode(text[:2000], normalize_embeddings=True)
        return embedding.tolist()

    @classmethod
    def unload(cls):
        """Release model memory if needed."""
        cls._model = None
