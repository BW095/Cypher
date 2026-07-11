from sentence_transformers import SentenceTransformer

class BGEWrapper:
    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5"):
        print(f"Loading embedding model: {model_name}...")
        self.model = SentenceTransformer(model_name)

    def embed_text(self, text: str) -> list[float]:
        # Generate embedding for a single string
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Generate embeddings for a list of strings (faster for chunks)
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()