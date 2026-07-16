"""
BGE embedding model wrapper.

The model is loaded once (CPU) and kept resident for the life of the
process — it's only ~400MB of RAM and is needed by every query and every
ingested document. Loading prefers the local HuggingFace cache
(local_files_only) so routine queries make zero network calls; the
download path is only taken on the very first run.
"""

import os
import threading

# Quiet HF background noise before sentence_transformers is imported.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class BGEWrapper:
    _model = None
    _model_name = None
    _lock = threading.Lock()

    def __init__(self, model_name: str = None):
        if model_name is None:
            from app.config import ModelConfig
            model_name = ModelConfig.BGE_MODEL_NAME
        self.model_name = model_name

    def _get_model(self):
        cls = type(self)
        with cls._lock:
            if cls._model is None or cls._model_name != self.model_name:
                cls._model = self._load(self.model_name)
                cls._model_name = self.model_name
            return cls._model

    @staticmethod
    def _load(model_name: str):
        from sentence_transformers import SentenceTransformer
        print(f"Loading BGE embedding model '{model_name}' (CPU, kept resident)...")
        try:
            # Offline-first: use the local cache without any HTTP round-trips.
            return SentenceTransformer(model_name, device="cpu", local_files_only=True)
        except TypeError:
            # Older sentence-transformers without local_files_only support.
            return SentenceTransformer(model_name, device="cpu")
        except Exception:
            print("  Not in local cache — downloading from HuggingFace (first run only)...")
            return SentenceTransformer(model_name, device="cpu")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a document's chunks. CPU keeps the GPU free for the LLM."""
        if not texts:
            return []
        model = self._get_model()
        embeddings = model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for semantic search.

        Uses the BGE-recommended query prefix so that query embeddings
        align better with passage embeddings in vector space.
        """
        prefixed = f"Represent this sentence for searching relevant passages: {text}"
        model = self._get_model()
        embedding = model.encode([prefixed], normalize_embeddings=True)
        return embedding[0].tolist()

    @classmethod
    def unload(cls):
        """Release the resident model (rarely needed — it lives in CPU RAM)."""
        import gc
        with cls._lock:
            cls._model = None
            cls._model_name = None
        gc.collect()
