from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from app.config import QdrantConfig
import uuid


class QdrantStorage:
    def __init__(self, host: str = "localhost", port: int = 6333, collection_name: str = "industrial_knowledge"):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.vector_size = QdrantConfig.VECTOR_SIZE  # 1024 for Titan Embed v2

        self._init_collection()

    def _init_collection(self):
        # Check if collection exists, if not, create it
        collections = self.client.get_collections().collections
        if not any(c.name == self.collection_name for c in collections):
            print(f"Creating Qdrant collection: {self.collection_name}")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
            )

    def store_chunks(self, chunks: list[dict], embeddings: list[list[float]]):
        points = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid4())
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=chunk  # Contains the text and metadata
                )
            )

        try:
            self.client.upsert(collection_name=self.collection_name, points=points)
        except Exception as e:
            # The collection can be deleted out from under a running process
            # (e.g. clear.py). Recreate it and retry once instead of failing
            # every ingestion until restart.
            print(f"[Qdrant] Upsert failed ({e}); ensuring collection exists and retrying...")
            self._init_collection()
            self.client.upsert(collection_name=self.collection_name, points=points)

    # ------------------------------------------------------------------
    # Retrieval methods
    # ------------------------------------------------------------------

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict]:
        """Semantic search: find the top-k most similar chunks to the query vector.

        Returns a list of dicts with keys: text, score, metadata.
        """
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            with_payload=True,
        )

        hits = []
        for point in results.points:
            payload = point.payload or {}
            hits.append({
                "text": payload.get("text", ""),
                "score": point.score,
                "metadata": payload.get("metadata", {}),
            })
        return hits

    def search_with_filter(
        self,
        query_vector: list[float],
        top_k: int = 5,
        file_type: str | None = None,
        source_path: str | None = None,
    ) -> list[dict]:
        """Semantic search with optional metadata filters."""
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue

        conditions = []
        if file_type:
            conditions.append(
                FieldCondition(key="metadata.file_type", match=MatchValue(value=file_type))
            )
        if source_path:
            conditions.append(
                FieldCondition(key="metadata.source", match=MatchValue(value=source_path))
            )

        query_filter = Filter(must=conditions) if conditions else None

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )

        hits = []
        for point in results.points:
            payload = point.payload or {}
            hits.append({
                "text": payload.get("text", ""),
                "score": point.score,
                "metadata": payload.get("metadata", {}),
            })
        return hits

    def delete_by_source(self, source_path: str):
        """Delete all chunks originating from a specific file (for re-ingestion)."""
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue

        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(key="metadata.source", match=MatchValue(value=source_path))
                ]
            ),
        )