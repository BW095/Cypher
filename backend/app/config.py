"""
Centralized configuration for the Cypher application (cloud deployment).

All configurable values live here. Services import from this module
instead of hardcoding connection strings and model paths.

Environment variables override defaults when set.

Cloud variant: local GGUF model paths replaced with Amazon Bedrock
model IDs. No GPU planning, no local model files needed.
"""

import os

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)


# ---------------------------------------------------------------------------
# Database connections
# ---------------------------------------------------------------------------
class QdrantConfig:
    HOST: str = os.getenv("QDRANT_HOST", "localhost")
    PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION", "industrial_knowledge")
    VECTOR_SIZE: int = int(os.getenv("VECTOR_SIZE", "1024"))  # Titan Embed v2 default


class Neo4jConfig:
    URI: str = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
    USER: str = os.getenv("NEO4J_USER", "neo4j")
    PASSWORD: str = os.getenv("NEO4J_PASSWORD", "password")
    DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")


class SQLiteConfig:
    DB_PATH: str = os.getenv(
        "SQLITE_DB_PATH",
        os.path.join(_BACKEND_DIR, "data", "app.db"),
    )


# ---------------------------------------------------------------------------
# Amazon Bedrock configuration
# ---------------------------------------------------------------------------
class BedrockConfig:
    REGION: str = os.getenv("AWS_REGION", "us-east-1")

    # Main chat model — Claude 3.5 Haiku (vision-capable, cost-effective)
    CHAT_MODEL_ID: str = os.getenv(
        "BEDROCK_CHAT_MODEL_ID",
        "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    )
    # Entity extraction model — same Haiku for cost savings
    EXTRACTION_MODEL_ID: str = os.getenv(
        "BEDROCK_EXTRACTION_MODEL_ID",
        "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    )
    # Embedding model — Titan Embed Text v2
    EMBED_MODEL_ID: str = os.getenv(
        "BEDROCK_EMBED_MODEL_ID",
        "amazon.titan-embed-text-v2:0",
    )
    # Generation parameters
    MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))
    TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))


# ---------------------------------------------------------------------------
# Retrieval parameters
# ---------------------------------------------------------------------------
class RetrievalConfig:
    VECTOR_TOP_K: int = int(os.getenv("VECTOR_TOP_K", "5"))
    GRAPH_SEARCH_DEPTH: int = int(os.getenv("GRAPH_SEARCH_DEPTH", "2"))
    MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))
    MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "5"))
    # Over-fetch this many vector hits, then rerank down to VECTOR_TOP_K.
    VECTOR_FETCH_K: int = int(os.getenv("VECTOR_FETCH_K", "15"))

    # Cross-encoder reranking. When on, the over-fetched candidates are scored
    # by a cross-encoder (query+passage together) — far more precise than the
    # lexical fallback. Runs on CPU to keep the GPU free for the LLM. Falls back
    # to the lexical reranker automatically if the model can't be loaded.
    USE_CROSS_ENCODER: bool = os.getenv("USE_CROSS_ENCODER", "true").lower() in ("1", "true", "yes")
    # Default to a small, fast cross-encoder (~80MB) that reranks well on CPU —
    # a good fit for a 6GB laptop. For higher accuracy set RERANK_MODEL to
    # "BAAI/bge-reranker-base" (~1.1GB, slower on CPU) once it's cached locally.
    RERANK_MODEL: str = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")


# ---------------------------------------------------------------------------
# Entity extraction (full-document windowing)
# ---------------------------------------------------------------------------
class ExtractionConfig:
    WINDOW_CHARS: int = int(os.getenv("EXTRACTION_WINDOW_CHARS", "2000"))
    WINDOW_OVERLAP: int = int(os.getenv("EXTRACTION_WINDOW_OVERLAP", "200"))
    # Cap windows so a 500-page manual can't spawn hundreds of LLM calls.
    MAX_WINDOWS: int = int(os.getenv("EXTRACTION_MAX_WINDOWS", "8"))
    # Max tokens generated PER WINDOW. A window's entity JSON rarely needs more
    # than ~1200 tokens; capping here stops the model (especially smaller ones)
    # from rambling to the 2048 ceiling, which is the dominant scan-time cost.
    # Truncated-JSON recovery salvages anything cut off, so lower is mostly free.
    MAX_TOKENS: int = int(os.getenv("EXTRACTION_MAX_TOKENS", "1280"))


# ---------------------------------------------------------------------------
# Server settings
# ---------------------------------------------------------------------------
class ServerConfig:
    HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("SERVER_PORT", "8000"))
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    ).split(",")
    # Directory for temporary uploaded files (browser sync)
    UPLOAD_DIR: str = os.getenv(
        "UPLOAD_DIR",
        os.path.join(_BACKEND_DIR, "data", "uploads"),
    )
