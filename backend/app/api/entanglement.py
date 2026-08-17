"""
Document Entanglement Graph API
================================
Exposes the document-level dependency graph and risk propagation engine.

Endpoints
---------
GET  /api/entanglement/graph
    Full document dependency graph (nodes = docs, edges = [:REFERENCES]).

POST /api/entanglement/risk
    Given a document path + event type, return all downstream at-risk documents.

POST /api/entanglement/status
    Set a document's status (active / revoked / expired / cancelled / suspended).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

router = APIRouter(prefix="/api/entanglement", tags=["Entanglement"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RiskRequest(BaseModel):
    path: str
    event: Literal["revoked", "expired", "cancelled", "suspended"] = "revoked"
    update_status: bool = True    # also write the status to Neo4j

class StatusRequest(BaseModel):
    path: str
    status: Literal["active", "revoked", "expired", "cancelled", "suspended"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_neo4j():
    from app.main import get_neo4j
    db = get_neo4j()
    if db is None:
        raise HTTPException(status_code=503, detail="Graph DB not ready.")
    return db


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/graph")
def get_entanglement_graph():
    """Return the full document-level dependency graph.

    Each node is an ingested Document with category, domain, and status.
    Each edge is a [:REFERENCES] link discovered from DOC_REFERENCE entities.
    """
    db = _get_neo4j()
    return db.get_entanglement_graph()


@router.post("/risk")
def get_risk_chain(req: RiskRequest):
    """Propagate risk from a revoked/expired document.

    Traverses all documents that depend (directly or transitively) on the
    given document and returns them as the at-risk list.

    If ``update_status=true`` (default), also writes the event type as the
    document's new status in Neo4j so the graph view reflects it.
    """
    db = _get_neo4j()
    if req.update_status:
        db.update_document_status(req.path, req.event)
    result = db.get_risk_chain(req.path)
    result["event"] = req.event
    return result


@router.post("/status")
def update_status(req: StatusRequest):
    """Manually set the status of a document node.

    Useful for marking a document as restored (active) after a revocation,
    or for flagging expired certificates discovered outside the pipeline.
    """
    db = _get_neo4j()
    ok = db.update_document_status(req.path, req.status)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not update document status.")
    return {"path": req.path, "status": req.status, "updated": True}
