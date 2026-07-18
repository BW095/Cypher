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
    MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))
    MAX_HISTORY_TURNS: int = int(os.getenv("MAX_HISTORY_TURNS", "5"))
    # Over-fetch this many vector hits, then rerank down to VECTOR_TOP_K.
    VECTOR_FETCH_K: int = int(os.getenv("VECTOR_FETCH_K", "15"))


# ---------------------------------------------------------------------------
# Entity extraction (full-document windowing)
# ---------------------------------------------------------------------------
class ExtractionConfig:
    WINDOW_CHARS: int = int(os.getenv("EXTRACTION_WINDOW_CHARS", "2000"))
    WINDOW_OVERLAP: int = int(os.getenv("EXTRACTION_WINDOW_OVERLAP", "200"))
    # Cap windows so a 500-page manual can't spawn hundreds of LLM calls.
    MAX_WINDOWS: int = int(os.getenv("EXTRACTION_MAX_WINDOWS", "8"))


# ---------------------------------------------------------------------------
# LLM generation parameters
# ---------------------------------------------------------------------------
class LLMConfig:
    MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1024"))
    TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    N_CTX: int = int(os.getenv("LLM_N_CTX", "4096"))
    SUBPROCESS_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "300"))

    # GPU offload: "auto" plans layers from free VRAM (hardware.py);
    # an integer forces that many layers (0 = CPU-only, like -1 used to force all).
    N_GPU_LAYERS: str = os.getenv("LLM_N_GPU_LAYERS", "auto")
    # VRAM headroom (MB) kept free for llama.cpp compute buffers when planning.
    VRAM_RESERVE_MB: int = int(os.getenv("LLM_VRAM_RESERVE_MB", "800"))
    # Unload the model after this many seconds of inactivity (0 = never unload).
    IDLE_UNLOAD_SECONDS: int = int(os.getenv("LLM_IDLE_UNLOAD_SECONDS", "600"))
    # Max seconds to wait for the model to load (CPU loads of 8B can be slow).
    LOAD_TIMEOUT: int = int(os.getenv("LLM_LOAD_TIMEOUT", "600"))
    # CPU threads for inference (0 = llama.cpp default).
    N_THREADS: int = int(os.getenv("LLM_N_THREADS", "0"))


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
