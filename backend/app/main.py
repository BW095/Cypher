"""
Cypher — FastAPI application entry point.

Creates singleton instances of all services, configures CORS for the
React frontend, includes all API routers, and manages startup/shutdown
lifecycle events.

Run with:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ServerConfig, QdrantConfig, Neo4jConfig
from app.api.models import HealthResponse

# ---------------------------------------------------------------------------
# Singleton service instances (shared across all requests)
# ---------------------------------------------------------------------------
_sqlite = None
_qdrant = None
_neo4j = None
_embedding_model = None
_llm = None
_query_engine = None
_pipeline = None

logger = logging.getLogger("cypher")


def get_sqlite():
    return _sqlite


def get_qdrant():
    return _qdrant


def get_neo4j():
    return _neo4j


def get_llm():
    return _llm


def get_query_engine():
    return _query_engine


def get_pipeline():
    return _pipeline


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic for the FastAPI application."""
    global _sqlite, _qdrant, _neo4j, _embedding_model, _llm, _query_engine, _pipeline

    logger.info("🚀 Starting Cypher AI Brain...")

    # 1. Initialize storage layer
    from app.storage.sqlite import SQLiteStorage
    from app.storage.qdrant import QdrantStorage
    from app.storage.neo4j import Neo4jStorage

    _sqlite = SQLiteStorage()
    logger.info("  ✅ SQLite initialized")

    try:
        _qdrant = QdrantStorage(
            host=QdrantConfig.HOST,
            port=QdrantConfig.PORT,
            collection_name=QdrantConfig.COLLECTION_NAME,
        )
        logger.info("  ✅ Qdrant connected")
    except Exception as e:
        logger.warning(f"  ⚠️ Qdrant connection failed: {e} — vector search will be unavailable")
        _qdrant = None

    try:
        _neo4j = Neo4jStorage(
            uri=Neo4jConfig.URI,
            user=Neo4jConfig.USER,
            password=Neo4jConfig.PASSWORD,
            database=Neo4jConfig.DATABASE,
        )
        logger.info("  ✅ Neo4j connected")
    except Exception as e:
        logger.warning(f"  ⚠️ Neo4j connection failed: {e} — graph search will be unavailable")
        _neo4j = None

    # 2. Initialize AI models
    from app.ai.embeddings import BGEWrapper
    from app.ai.llm import LLMWrapper

    _embedding_model = BGEWrapper()
    _llm = LLMWrapper()
    logger.info("  ✅ AI models configured (lazy-loaded on first use)")

    # 3. Initialize retrieval engine
    from app.retrieval.query_engine import QueryEngine

    _query_engine = QueryEngine(
        embedding_model=_embedding_model,
        qdrant_db=_qdrant,
        neo4j_db=_neo4j,
        llm=_llm,
    )
    logger.info("  ✅ Query engine initialized")

    # 4. Initialize ingestion pipeline
    from app.ingestion.pipeline import IngestionPipeline

    _pipeline = IngestionPipeline()
    # Override with our shared singletons so we don't create duplicate connections
    if _sqlite:
        _pipeline.tracker = _sqlite
    if _qdrant:
        _pipeline.qdrant_db = _qdrant
    if _neo4j:
        _pipeline.neo4j_db = _neo4j
    if _embedding_model:
        _pipeline.embedding_model = _embedding_model
    logger.info("  ✅ Ingestion pipeline initialized")

    # Resume watchers for previously-tracked folders, so a restart doesn't leave
    # them showing "watching" with no live watcher (and picks up offline edits).
    try:
        from app.api.ingestion import start_tracked_watchers
        start_tracked_watchers()
        logger.info("  ✅ Resumed folder watchers")
    except Exception as e:
        logger.warning(f"  ⚠️ Could not resume folder watchers: {e}")

    logger.info("🧠 Cypher AI Brain is ready!")

    yield  # Application is running

    # --- Shutdown ---
    logger.info("🛑 Shutting down Cypher AI Brain...")

    if _neo4j:
        try:
            _neo4j.close()
            logger.info("  ✅ Neo4j connection closed")
        except Exception:
            pass

    logger.info("👋 Shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Cypher AI Brain",
    description=(
        "Industrial AI knowledge engine that understands company documents, "
        "connects them through a knowledge graph, and provides intelligent "
        "answers grounded in your data."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=ServerConfig.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Include API routers
# ---------------------------------------------------------------------------
from app.api.chat import router as chat_router
from app.api.ingestion import router as ingestion_router
from app.api.documents import router as documents_router
from app.api.graph import router as graph_router
from app.api.compliance import router as compliance_router

app.include_router(chat_router)
app.include_router(ingestion_router)
app.include_router(documents_router)
app.include_router(graph_router)
app.include_router(compliance_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check the status of all connected services."""
    services = {}

    services["sqlite"] = "ok" if _sqlite else "unavailable"
    services["qdrant"] = "ok" if _qdrant else "unavailable"
    services["neo4j"] = "ok" if _neo4j else "unavailable"
    services["embeddings"] = "configured" if _embedding_model else "unavailable"

    services["llm"] = "bedrock" if _llm else "unavailable"

    overall = "ok" if all(
        v.startswith(("ok", "configured", "loaded", "bedrock")) for v in services.values()
    ) else "degraded"

    return HealthResponse(status=overall, services=services)


# ---------------------------------------------------------------------------
# Logging config
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)