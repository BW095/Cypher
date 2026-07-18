"""
Vector Retriever — semantic search over the Qdrant vector store.

Takes a user query, embeds it with BGE, and finds the most similar
document chunks stored during ingestion.
"""

import sys
from app.ai.embeddings import BGEWrapper
from app.storage.qdrant import QdrantStorage
from app.config import RetrievalConfig
from app.retrieval.reranker import rerank, rerank_cross_encoder


class VectorRetriever:
    def __init__(self, embedding_model: BGEWrapper = None, qdrant_db: QdrantStorage = None):
        self.embedding_model = embedding_model or BGEWrapper()
        self.qdrant_db = qdrant_db or QdrantStorage()

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        file_type: str | None = None,
        source_path: str | None = None,
    ) -> list[dict]:
        """Retrieve the most relevant chunks for a query.

        Returns a list of dicts:
            {text: str, score: float, source: str, file_type: str, metadata: dict}
        """
        top_k = top_k or RetrievalConfig.VECTOR_TOP_K
        # Over-fetch, then rerank down to top_k so exact tag/code matches can
        # climb above chunks that are merely close in embedding space.
        fetch_k = max(top_k, RetrievalConfig.VECTOR_FETCH_K)

        print(f"[VectorRetriever] Embedding query: '{query[:80]}...'")
        sys.stdout.flush()

        # 1. Embed the query
        query_vector = self.embedding_model.embed_query(query)

        # 2. Search Qdrant (fetch a wider candidate pool for reranking)
        if file_type or source_path:
            raw_hits = self.qdrant_db.search_with_filter(
                query_vector=query_vector,
                top_k=fetch_k,
                file_type=file_type,
                source_path=source_path,
            )
        else:
            raw_hits = self.qdrant_db.search(
                query_vector=query_vector,
                top_k=fetch_k,
            )

        # 3. Normalize into a clean format
        candidates = []
        for hit in raw_hits:
            metadata = hit.get("metadata", {})
            candidates.append({
                "text": hit.get("text", ""),
                "score": hit.get("score", 0.0),
                "source": metadata.get("source", "unknown"),
                "file_type": metadata.get("file_type", "unknown"),
                "metadata": metadata,
            })

        # 4. Rerank the candidate pool and trim to top_k. Prefer the
        #    cross-encoder (query+passage scored together); fall back to the
        #    lexical reranker if it's disabled or the model can't be loaded.
        results = None
        rerank_kind = "lexical"
        if RetrievalConfig.USE_CROSS_ENCODER:
            results = rerank_cross_encoder(
                query, candidates, top_k=top_k, model_name=RetrievalConfig.RERANK_MODEL,
            )
            if results is not None:
                rerank_kind = "cross-encoder"
        if results is None:
            results = rerank(query, candidates, top_k=top_k)

        if results:
            print(f"[VectorRetriever] {len(candidates)} candidates -> top {len(results)} "
                  f"after {rerank_kind} rerank (top vector {results[0]['score']:.3f}, "
                  f"rerank {results[0].get('rerank_score', 0):.3f})")
        else:
            print("[VectorRetriever] No chunks found")
        sys.stdout.flush()

        return results
