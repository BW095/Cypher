"""
Embedding model wrapper — Amazon Bedrock Titan Text Embeddings v2.

Replaces the local sentence-transformers BGE model with Bedrock API
calls. The public API (embed_batch / embed_query) is unchanged, so
the ingestion pipeline and vector retriever work without modification.

Titan Embed Text v2 outputs 1024-dimensional vectors by default.
"""

import json
import boto3

from app.config import BedrockConfig, QdrantConfig


class BGEWrapper:
    """Bedrock embedding wrapper.

    Named BGEWrapper for backward compatibility — the rest of the
    codebase imports this name.
    """

    def __init__(self, model_name: str = None):
        # model_name kept for API compat; ignored in Bedrock mode
        self.model_id = BedrockConfig.EMBED_MODEL_ID
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=BedrockConfig.REGION,
            )
        return self._client

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document chunks. Returns a list of vectors."""
        if not texts:
            return []
        results = []
        # Titan Embed accepts one text at a time; batch serially.
        # For large batches this is fine — Bedrock latency is ~50ms/call.
        for text in texts:
            vec = self._embed_one(text, input_type="search_document")
            if vec:
                results.append(vec)
            else:
                # Fallback: zero vector so indices stay aligned
                results.append([0.0] * QdrantConfig.VECTOR_SIZE)
        return results

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string for semantic search."""
        vec = self._embed_one(text, input_type="search_query")
        return vec if vec else [0.0] * QdrantConfig.VECTOR_SIZE

    def _embed_one(self, text: str, input_type: str = "search_document") -> list[float] | None:
        """Call Titan Embed Text v2 for a single text."""
        try:
            body = {
                "inputText": text[:8000],  # Titan v2 max ~8K tokens
                "dimensions": QdrantConfig.VECTOR_SIZE,
                "normalize": True,
            }
            response = self.client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            result = json.loads(response["body"].read())
            return result.get("embedding")
        except Exception as e:
            print(f"[Bedrock Embed] Error: {e}")
            return None

    @classmethod
    def unload(cls):
        """No-op for Bedrock — nothing local to unload."""
        pass
