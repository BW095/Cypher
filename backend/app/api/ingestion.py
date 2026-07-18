"""
Ingestion API routes — start/stop folder watching, check status.
"""

import os
import threading
from fastapi import APIRouter, HTTPException

from app.api.models import (
    IngestRequest, IngestStopRequest, IngestStatus, TrackedFolder,
)

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])

# Track active watcher threads so we can stop them
_active_watchers: dict[str, object] = {}  # folder_path -> DirectoryWatcher
_watcher_lock = threading.Lock()


def get_deps():
    """Lazy import to avoid circular imports at module load time."""
    from app.main import get_pipeline, get_sqlite
    return get_pipeline(), get_sqlite()


# -------------------------------------------------------------------------
# POST /api/ingest/start — start tracking a folder
# -------------------------------------------------------------------------
@router.post("/start")
async def start_ingestion(req: IngestRequest):
    """Start tracking and ingesting files from a folder."""
    pipeline, db = get_deps()

    folder = os.path.abspath(req.folder_path)

    if not os.path.isdir(folder):
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {folder}")

    with _watcher_lock:
        if folder in _active_watchers:
            return {"status": "already_running", "folder": folder}

    # Register in SQLite
    db.add_folder(folder)

    # Start watcher in a background thread
    from app.ingestion.watcher import DirectoryWatcher

    watcher = DirectoryWatcher(directory_to_watch=folder, pipeline=pipeline)

    def _run_watcher():
        try:
            watcher.start()
        except Exception as e:
            print(f"[Ingestion] Watcher for {folder} crashed: {e}")

    thread = threading.Thread(target=_run_watcher, daemon=True, name=f"watcher-{folder}")

    with _watcher_lock:
        _active_watchers[folder] = watcher

    thread.start()

    return {"status": "started", "folder": folder}


# -------------------------------------------------------------------------
# POST /api/ingest/stop — stop watching a folder
# -------------------------------------------------------------------------
@router.post("/stop")
async def stop_ingestion(req: IngestStopRequest):
    """Stop watching a folder (does not delete ingested data)."""
    _, db = get_deps()

    folder = os.path.abspath(req.folder_path)

    with _watcher_lock:
        watcher = _active_watchers.pop(folder, None)

    if watcher is None:
        raise HTTPException(status_code=404, detail=f"No active watcher for: {folder}")

    # Stop the watch loop, its observer, and its ingestion queue worker.
    try:
        watcher.stop()
    except Exception:
        pass

    db.deactivate_folder(folder)

    return {"status": "stopped", "folder": folder}


# -------------------------------------------------------------------------
# GET /api/ingest/status — overall ingestion statistics
# -------------------------------------------------------------------------
@router.get("/status", response_model=IngestStatus)
async def get_status():
    """Get overall ingestion statistics."""
    _, db = get_deps()

    stats = db.get_ingestion_stats()
    folders = db.list_folders()

    return IngestStatus(
        tracked_folders=[
            TrackedFolder(
                path=f["path"],
                added_at=f["added_at"],
                is_active=bool(f.get("is_active", 0)),
            )
            for f in folders
        ],
        total_documents=stats["total"],
        completed=stats["completed"],
        processing=stats["processing"],
        failed=stats["failed"],
    )


# -------------------------------------------------------------------------
# GET /api/ingest/folders — list tracked folders
# -------------------------------------------------------------------------
@router.get("/folders", response_model=list[TrackedFolder])
async def list_folders():
    """List all tracked folders."""
    _, db = get_deps()

    folders = db.list_folders()
    return [
        TrackedFolder(
            path=f["path"],
            added_at=f["added_at"],
            is_active=bool(f.get("is_active", 0)),
        )
        for f in folders
    ]
