"""
Graph API routes — query and explore the knowledge graph.
"""

from fastapi import APIRouter

from app.api.models import (
    GraphQueryRequest, GraphResponse, GraphNode, GraphEdge, GraphStatsResponse,
)

router = APIRouter(prefix="/api/graph", tags=["Knowledge Graph"])


def get_deps():
    """Lazy import to avoid circular imports at module load time."""
    from app.main import get_neo4j
    return get_neo4j()


# -------------------------------------------------------------------------
# POST /api/graph/query — query the graph for an entity
# -------------------------------------------------------------------------
@router.post("/query", response_model=GraphResponse)
async def query_graph(req: GraphQueryRequest):
    """Query the knowledge graph for an entity and its connections."""
    neo4j_db = get_deps()

    result = neo4j_db.find_related_entities(
        entity_name=req.entity_name,
        depth=req.depth,
    )

    return GraphResponse(
        nodes=[
            GraphNode(
                id=n.get("id", ""),
                name=n.get("name", ""),
                type=n.get("type", "Unknown"),
                description=n.get("description", ""),
            )
            for n in result.get("nodes", [])
        ],
        edges=[
            GraphEdge(
                source=e.get("source", ""),
                target=e.get("target", ""),
                type=e.get("type", ""),
            )
            for e in result.get("edges", [])
        ],
        source_documents=result.get("source_documents", []),
    )


# -------------------------------------------------------------------------
# GET /api/graph/stats — graph statistics
# -------------------------------------------------------------------------
@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats():
    """Get high-level statistics about the knowledge graph."""
    neo4j_db = get_deps()
    stats = neo4j_db.get_graph_stats()

    return GraphStatsResponse(
        total_entities=stats.get("total_entities", 0),
        total_relationships=stats.get("total_relationships", 0),
        total_documents=stats.get("total_documents", 0),
        entity_types=stats.get("entity_types", {}),
    )
