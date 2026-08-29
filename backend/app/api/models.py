"""
Pydantic models for all API request/response schemas.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ==========================================================================
# Chat Models
# ==========================================================================

class ChatRequest(BaseModel):
    """User sends a chat message."""
    user_message: str = Field(..., min_length=1, description="The user's question or prompt")
    session_id: Optional[str] = Field(None, description="Existing session ID. None creates a new session.")


class SourceReference(BaseModel):
    """A document source cited in an answer."""
    file_path: str
    file_type: str = ""
    chunk_text: str = ""
    relevance_score: float = 0.0
    cited: bool = False  # True when the answer text actually references this file


class ConfidenceInfo(BaseModel):
    """How much to trust an answer, derived from retrieval/citation signals."""
    score: float = 0.0            # 0..1
    label: str = "Low"           # High | Medium | Low
    reasons: List[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """AI response to a chat message."""
    answer: str
    sources: List[SourceReference] = Field(default_factory=list)
    session_id: str
    entities_referenced: List[str] = Field(default_factory=list)
    confidence: ConfidenceInfo = Field(default_factory=ConfidenceInfo)


class ChatMessage(BaseModel):
    """A single message in a chat session."""
    role: str  # "user" or "assistant"
    content: str
    sources: List[SourceReference] = Field(default_factory=list)
    timestamp: str


class ChatSession(BaseModel):
    """Summary of a chat session."""
    id: str
    title: str
    created_at: str
    last_message_at: str
    message_count: int = 0


class ChatSessionDetail(BaseModel):
    """Full chat session with all messages."""
    session: ChatSession
    messages: List[ChatMessage]


# ==========================================================================
# Ingestion Models
# ==========================================================================

class IngestRequest(BaseModel):
    """Request to start tracking and ingesting a folder."""
    folder_path: str = Field(..., description="Absolute path to the folder to track")


class IngestStopRequest(BaseModel):
    """Request to stop tracking a folder."""
    folder_path: str


class TrackedFolder(BaseModel):
    """A folder being tracked for ingestion."""
    path: str
    added_at: str
    is_active: bool = True


class IngestStatus(BaseModel):
    """Overall ingestion statistics."""
    tracked_folders: List[TrackedFolder] = Field(default_factory=list)
    total_documents: int = 0
    completed: int = 0
    processing: int = 0
    failed: int = 0


# ==========================================================================
# Document Models
# ==========================================================================

class DocumentInfo(BaseModel):
    """Information about an ingested document."""
    id: int
    file_path: str
    file_type: str
    status: str
    ingested_at: str


class DocumentListResponse(BaseModel):
    """List of all documents."""
    documents: List[DocumentInfo]
    total: int


# ==========================================================================
# Graph Models
# ==========================================================================

class GraphQueryRequest(BaseModel):
    """Query the knowledge graph for an entity."""
    entity_name: str = Field(..., description="Entity name to search for")
    depth: int = Field(2, ge=1, le=4, description="Traversal depth (hops)")


class GraphNode(BaseModel):
    """A node in the knowledge graph."""
    id: str
    name: str
    type: str
    description: str = ""
    degree: int = 0  # number of connected relationships (for sizing in the viz)


class GraphEdge(BaseModel):
    """An edge in the knowledge graph."""
    source: str  # source node id
    target: str  # target node id
    type: str


class GraphResponse(BaseModel):
    """Knowledge graph query result."""
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    source_documents: List[str] = Field(default_factory=list)


class GraphFullResponse(BaseModel):
    """The whole knowledge graph (capped) for visualization."""
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


class GraphStatsResponse(BaseModel):
    """High-level graph statistics."""
    total_entities: int = 0
    total_relationships: int = 0
    total_documents: int = 0
    entity_types: Dict[str, int] = Field(default_factory=dict)


# ==========================================================================
# Compliance Models
# ==========================================================================

class ComplianceRegulation(BaseModel):
    """Coverage assessment for one regulation."""
    name: str
    description: str = ""
    status: str  # covered | partial | gap
    linked_procedures: List[str] = Field(default_factory=list)
    linked_equipment: List[str] = Field(default_factory=list)
    evidence_documents: List[str] = Field(default_factory=list)
    gap_reason: str = ""


class ComplianceSummary(BaseModel):
    total: int = 0
    covered: int = 0
    partial: int = 0
    gaps: int = 0


class ComplianceResponse(BaseModel):
    """Compliance gap analysis result."""
    summary: ComplianceSummary = Field(default_factory=ComplianceSummary)
    regulations: List[ComplianceRegulation] = Field(default_factory=list)
    narrative: Optional[str] = None


# ==========================================================================
# Health Check
# ==========================================================================

class HealthResponse(BaseModel):
    """API health check response."""
    status: str = "ok"
    services: Dict[str, str] = Field(default_factory=dict)
