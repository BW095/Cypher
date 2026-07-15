import gc
import torch
from sentence_transformers import SentenceTransformer


class BGEWrapper:
    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5"):
        self.model_name = model_name

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Loads BGE model on CPU, embeds the entire document's chunks, and unloads.

        We explicitly use CPU to keep the GPU free for the LLM and vision model,
        which need the full 6GB VRAM. BGE-base is small (~400MB) and fast on CPU.
        """
        if not texts:
            return []

        print(f"Loading BGE Embedding model (CPU) for batch of {len(texts)} chunks...")
        model = SentenceTransformer(self.model_name, device="cpu")

        try:
            embeddings = model.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()
        finally:
            del model
            gc.collect()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for semantic search.

        Uses the BGE-recommended query prefix so that query embeddings
        align better with passage embeddings in vector space.
        Same load/unload pattern as embed_batch — CPU only.
        """
        prefixed = f"Represent this sentence for searching relevant passages: {text}"

        print(f"Loading BGE Embedding model (CPU) for single query...")
        model = SentenceTransformer(self.model_name, device="cpu")

        try:
            embedding = model.encode([prefixed], normalize_embeddings=True)
            return embedding[0].tolist()
        finally:
            del model
            gc.collect()