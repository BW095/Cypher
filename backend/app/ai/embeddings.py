import gc
import torch
from sentence_transformers import SentenceTransformer


class BGEWrapper:
    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5"):
        self.model_name = model_name

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Loads BGE model, embeds the entire document's chunks, and unloads."""
        if not texts:
            return []

        print(f"Loading BGE Embedding model for batch of {len(texts)} chunks...")
        model = SentenceTransformer(self.model_name)

        try:
            embeddings = model.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()
        finally:
            # Flush Memory
            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()