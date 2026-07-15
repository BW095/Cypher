"""
Centralized configuration for the Cypher application.

All configurable values live here. Services import from this module
instead of hardcoding connection strings and model paths.

Environment variables override defaults when set.
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
    VECTOR_SIZE: int = 768  # BAAI/bge-base-en-v1.5 output dimension


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
# Model paths (local GGUF models)
# ---------------------------------------------------------------------------
class ModelConfig:
    QWEN_MODEL_PATH: str = os.getenv(
        "QWEN_MODEL_PATH",
        os.path.join(_PROJECT_ROOT, "models", "Qwen3VL-8B-Instruct-Q4_K_M.gguf"),
    )
    CLIP_PROJECTOR_PATH: str = os.getenv(
        "CLIP_PROJECTOR_PATH",
        os.path.join(_PROJECT_ROOT, "models", "mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf"),
    )
    BGE_MODEL_NAME: str = os.getenv("BGE_MODEL_NAME", "BAAI/bge-base-en-v1.5")


# ---------------------------------------------------------------------------
# Retrieval parameters
# ---------------------------------------------------------------------------
class RetrievalConfig:
    VECTOR_TOP_K: int = int(os.getenv("VECTOR_TOP_K", "5"))
    GRAPH_SEARCH_DEPTH: int = int(os.getenv("GRAPH_SEARCH_DEPTH", "2"))
    MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "3000"))
    MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "5"))


# ---------------------------------------------------------------------------
# LLM generation parameters
# ---------------------------------------------------------------------------
class LLMConfig:
    MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))
    TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    N_CTX: int = int(os.getenv("LLM_N_CTX", "4096"))
    SUBPROCESS_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "300"))


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
