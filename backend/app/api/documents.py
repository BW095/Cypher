"""
Document API routes — list and query ingested documents.
"""

from fastapi import APIRouter

from app.api.models import DocumentInfo, DocumentListResponse

router = APIRouter(prefix="/api/documents", tags=["Documents"])


def get_deps():
    """Lazy import to avoid circular imports at module load time."""
    from app.main import get_sqlite
    return get_sqlite()


# -------------------------------------------------------------------------
# GET /api/documents — list all ingested documents
# -------------------------------------------------------------------------
@router.get("", response_model=DocumentListResponse)
async def list_documents():
    """List all ingested documents with their status."""
    db = get_deps()
    docs = db.get_all_documents()

    return DocumentListResponse(
        documents=[
            DocumentInfo(
                id=d["id"],
                file_path=d["file_path"],
                file_type=d.get("file_type", "unknown"),
                status=d.get("status", "unknown"),
                ingested_at=str(d.get("ingested_at", "")),
            )
            for d in docs
        ],
        total=len(docs),
    )
