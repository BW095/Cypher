"""
Document API routes — list and query ingested documents.
"""

import os
import mimetypes

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

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


# -------------------------------------------------------------------------
# GET /api/documents/open — serve an original source file
# -------------------------------------------------------------------------
@router.get("/open")
async def open_document(
    path: str = Query(..., description="Absolute path of the tracked file"),
    download: bool = Query(False, description="Force download instead of inline view"),
):
    """Return the original file so answers can link back to their sources.

    Only files that were actually ingested (present in the tracker) are
    served — this prevents the endpoint from reading arbitrary paths.
    """
    db = get_deps()

    tracked = {d["file_path"] for d in db.get_all_documents()}
    if path not in tracked:
        raise HTTPException(status_code=404, detail="File is not a tracked document.")
    if not os.path.isfile(path):
        raise HTTPException(status_code=410, detail="File no longer exists on disk.")

    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    filename = os.path.basename(path)
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type=disposition,
    )
