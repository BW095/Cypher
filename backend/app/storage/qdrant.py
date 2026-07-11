from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
import uuid


class QdrantStorage:
    def __init__(self, host: str = "localhost", port: int = 6333, collection_name: str = "industrial_knowledge"):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.vector_size = 768  # BAAI bge-base-en-v1.5 outputs 768 dimensions

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

        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )