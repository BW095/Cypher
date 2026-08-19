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


def _start_watcher(folder: str, pipeline) -> bool:
    """Start a background watcher for `folder` (idempotent). Returns True if a
    new watcher was started, False if one was already running."""
    from app.ingestion.watcher import DirectoryWatcher

    with _watcher_lock:
        if folder in _active_watchers:
            return False

    watcher = DirectoryWatcher(directory_to_watch=folder, pipeline=pipeline)

    def _run_watcher():
        try:
            watcher.start()
        except Exception as e:
            print(f"[Ingestion] Watcher for {folder} crashed: {e}")

    with _watcher_lock:
        _active_watchers[folder] = watcher
    threading.Thread(target=_run_watcher, daemon=True, name=f"watcher-{folder}").start()
    return True


def start_tracked_watchers():
    """Re-start watchers for every active tracked folder. Called on app startup
    so a restart doesn't leave folders showing 'watching' with no live watcher
    (which also broke stop/remove)."""
    pipeline, db = get_deps()
    if pipeline is None or db is None:
        return
    for f in db.list_folders():
        if not f.get("is_active", 1):
            continue
        folder = os.path.abspath(f["path"])
        if not os.path.isdir(folder):
            print(f"[Ingestion] Tracked folder no longer exists, skipping: {folder}")
            continue
        try:
            _start_watcher(folder, pipeline)
            print(f"[Ingestion] Resumed watcher for {folder}")
        except Exception as e:
            print(f"[Ingestion] Could not resume watcher for {folder}: {e}")


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

    # Register in SQLite and start the watcher.
    db.add_folder(folder)
    _start_watcher(folder, pipeline)

    return {"status": "started", "folder": folder}


def _stop_watcher(folder: str):
    """Stop and drop a folder's watcher if one is running (no-op otherwise)."""
    with _watcher_lock:
        watcher = _active_watchers.pop(folder, None)
    if watcher is not None:
        try:
            watcher.stop()
        except Exception:
            pass


# -------------------------------------------------------------------------
# POST /api/ingest/stop — pause watching a folder (keeps ingested data)
# -------------------------------------------------------------------------
@router.post("/stop")
async def stop_ingestion(req: IngestStopRequest):
    """Stop watching a folder but keep its ingested data.

    Graceful: if no live watcher exists (e.g. after a server restart), the
    folder is still marked inactive instead of erroring.
    """
    _, db = get_deps()
    folder = os.path.abspath(req.folder_path)
    _stop_watcher(folder)
    db.deactivate_folder(folder)
    return {"status": "stopped", "folder": folder}


# -------------------------------------------------------------------------
# POST /api/ingest/remove — untrack a folder AND delete its ingested knowledge
# -------------------------------------------------------------------------
@router.post("/remove")
async def remove_folder(req: IngestStopRequest):
    """Fully remove a tracked folder: stop its watcher, purge every document it
    ingested (vectors + graph + tracking rows), and drop it from the list.

    Works whether or not a live watcher exists (restart-safe)."""
    pipeline, db = get_deps()
    folder = os.path.abspath(req.folder_path)

    _stop_watcher(folder)

    removed = 0
    if pipeline is not None:
        try:
            removed = pipeline.delete_folder(folder)
        except Exception as e:
            print(f"[Ingestion] Error purging documents for {folder}: {e}")

    db.remove_folder(folder)

    return {"status": "removed", "folder": folder, "documents_removed": removed}


# -------------------------------------------------------------------------
# POST /api/ingest/flush-caches — drop in-memory retrieval caches
# -------------------------------------------------------------------------
@router.post("/flush-caches")
async def flush_caches():
    """Invalidate the running backend's in-memory retrieval caches.

    The graph retriever caches entity names and document paths for ~60s
    (see Neo4jStorage). An external reset (clear.py) wipes the databases in
    a separate process, so those caches keep the just-deleted files
    'alive' until the TTL lapses — which shows up as chat referencing
    documents that no longer exist. clear.py calls this best-effort right
    after wiping so a full backend restart isn't required for a clean state.
    """
    pipeline, _ = get_deps()
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not ready")
    try:
        pipeline.neo4j_db.invalidate_entity_cache()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cache flush failed: {e}")
    return {"status": "flushed"}


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
