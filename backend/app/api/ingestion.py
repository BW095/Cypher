"""
Ingestion API routes — start/stop folder watching, check status,
and browser-based file upload/sync.
"""

import os
import hashlib
import threading
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from typing import Optional

from app.api.models import (
    IngestRequest, IngestStopRequest, IngestStatus, TrackedFolder,
)
from app.config import ServerConfig

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


# =========================================================================
# Browser-driven file upload & sync (File System Access API)
# =========================================================================

def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -------------------------------------------------------------------------
# POST /api/ingest/upload — upload a single file from the browser
# -------------------------------------------------------------------------
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    local_path: str = Form(...),
    content_hash: Optional[str] = Form(None),
):
    """Accept a file upload from the browser's File System Access API.

    `local_path` is the relative path inside the user's connected folder
    (e.g. "reports/pump_manual.pdf"). It's used as the document key in
    Qdrant, Neo4j, and SQLite so the UI can later match it for sync.

    `content_hash` (optional) is the SHA-256 the browser computed. If it
    matches what's already stored, the file is skipped (no re-ingest).
    """
    pipeline, db = get_deps()
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Ingestion pipeline not initialized")

    # Normalize the path key — prefix with "browser://" to distinguish
    # from server-side paths
    path_key = f"browser://{local_path}"

    # Read file bytes
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    # Content-hash dedup: skip if unchanged
    file_hash = content_hash or _hash_bytes(file_bytes)
    if db.get_document_status(path_key) == "completed" \
            and db.get_document_hash(path_key) == file_hash:
        return {"status": "unchanged", "file": file.filename, "path": path_key}

    # Save to upload dir
    upload_dir = ServerConfig.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    # Preserve directory structure inside uploads
    dest_dir = os.path.join(upload_dir, os.path.dirname(local_path))
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(upload_dir, local_path)

    with open(dest_path, "wb") as f:
        f.write(file_bytes)

    # Run through the ingestion pipeline in a background thread
    # (pipeline.process_file is synchronous and can be slow)
    def _ingest():
        try:
            # Temporarily monkey-patch the file path in pipeline results
            # so the document is tracked under the browser:// key
            pipeline.process_file_as(dest_path, path_key, file_hash)
        except Exception as e:
            print(f"[Upload] Ingestion failed for {local_path}: {e}")

    threading.Thread(target=_ingest, daemon=True).start()

    return {
        "status": "queued",
        "file": file.filename,
        "path": path_key,
    }


# -------------------------------------------------------------------------
# DELETE /api/ingest/file — remove a single file's knowledge
# -------------------------------------------------------------------------
@router.delete("/file")
async def remove_file(local_path: str = Query(...)):
    """Purge a single file from all stores (Qdrant + Neo4j + SQLite).

    Called by the browser sync when a file is deleted from the local folder.
    """
    pipeline, _ = get_deps()
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")

    path_key = f"browser://{local_path}"
    try:
        pipeline.delete_file(path_key)
    except Exception as e:
        print(f"[Upload] Delete failed for {local_path}: {e}")

    # Also remove the physical upload if it exists
    dest_path = os.path.join(ServerConfig.UPLOAD_DIR, local_path)
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except OSError:
            pass

    return {"status": "deleted", "path": path_key}


# -------------------------------------------------------------------------
# POST /api/ingest/file-hashes — batch check which files need re-upload
# -------------------------------------------------------------------------
@router.post("/file-hashes")
async def check_file_hashes(payload: dict):
    """Accept a dict of {local_path: sha256_hash} from the browser.

    Returns which files need uploading (new or changed) and which are
    already up-to-date. Also returns paths that exist on the server but
    NOT in the browser's dict (i.e. deleted files that should be purged).

    Request body: {"files": {"reports/a.pdf": "abc123...", ...}}
    """
    _, db = get_deps()
    if db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    browser_files = payload.get("files", {})
    needs_upload = []
    up_to_date = []
    server_deleted = []

    # Check each browser file against what we have
    for local_path, browser_hash in browser_files.items():
        path_key = f"browser://{local_path}"
        status = db.get_document_status(path_key)
        stored_hash = db.get_document_hash(path_key)

        if status == "completed" and stored_hash == browser_hash:
            up_to_date.append(local_path)
        else:
            needs_upload.append(local_path)

    # Find files tracked on the server under browser:// that the browser
    # no longer has (deleted locally)
    all_docs = db.get_all_documents()
    for doc in all_docs:
        fp = doc.get("file_path", "")
        if fp.startswith("browser://"):
            rel_path = fp[len("browser://"):]
            if rel_path not in browser_files:
                server_deleted.append(rel_path)

    return {
        "needs_upload": needs_upload,
        "up_to_date": up_to_date,
        "server_deleted": server_deleted,
    }

