"""
File Upload API
===============
POST /api/upload — accept multipart file uploads, save to a per-session
upload directory, and immediately queue them through the ingestion pipeline.

Key design decisions vs. v1:
- process_file() is CPU/IO-bound and synchronous.  Calling it inline inside an
  async endpoint blocks the entire uvicorn event loop.  We fire a background
  thread per file (same pattern as DirectoryWatcher) and return "queued"
  immediately so the HTTP response is fast.
- ZIP archives are extracted first; each supported file inside is queued.
- Unsupported file types are rejected before saving.
- The upload directory is set via UPLOAD_DIR env var
  (default: backend/data/uploads/).
"""

import os
import shutil
import threading
import zipfile
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

logger = logging.getLogger("cypher.api.upload")

router = APIRouter(prefix="/api/upload", tags=["Upload"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_DEFAULT_UPLOAD_DIR = os.path.join(_BACKEND_DIR, "data", "uploads")
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", _DEFAULT_UPLOAD_DIR)

_MAX_FILE_SIZE_MB = int(os.getenv("UPLOAD_MAX_MB", "200"))
_MAX_FILE_SIZE_BYTES = _MAX_FILE_SIZE_MB * 1024 * 1024

# Extensions the pipeline dispatcher handles (mirrors Dispatcher._EXTENSION_MAP)
_SUPPORTED_EXTS = {
    ".pdf",
    ".png", ".jpg", ".jpeg", ".tiff", ".bmp",
    ".mp4", ".mkv", ".avi", ".mov",
    ".mp3", ".wav", ".m4a", ".flac",
    ".xlsx", ".xls", ".csv",
    ".docx", ".doc", ".pptx", ".ppt", ".odt", ".html", ".txt",
    ".eml", ".msg",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ext(filename: str) -> str:
    return os.path.splitext(filename.lower())[1]


def _is_supported(filename: str) -> bool:
    return _ext(filename) in _SUPPORTED_EXTS


def _make_slot() -> str:
    """Create a fresh timestamped directory under UPLOAD_DIR."""
    slot = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(UPLOAD_DIR, slot)
    os.makedirs(path, exist_ok=True)
    return path


def _unique_dest(directory: str, filename: str) -> str:
    """Return a path inside *directory* that doesn't already exist."""
    dest = os.path.join(directory, filename)
    if not os.path.exists(dest):
        return dest
    base, ext = os.path.splitext(filename)
    i = 1
    while True:
        candidate = os.path.join(directory, f"{base}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _extract_zip(zip_path: str, dest_dir: str) -> List[str]:
    """Extract a ZIP and return absolute paths of all supported files inside."""
    collected: List[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                safe_name = os.path.basename(member)
                if not safe_name or not _is_supported(safe_name):
                    continue
                dest = _unique_dest(dest_dir, safe_name)
                with zf.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                collected.append(dest)
    except zipfile.BadZipFile as exc:
        logger.warning(f"[Upload] Bad ZIP: {zip_path} — {exc}")
    return collected


def _run_ingestion(file_path: str, pipeline) -> None:
    """Run process_file in a daemon thread — non-blocking for the caller."""
    def _worker():
        try:
            pipeline.process_file(file_path)
        except Exception as exc:
            logger.error(f"[Upload] Ingestion thread failed for {file_path}: {exc}")

    thread = threading.Thread(
        target=_worker,
        name=f"upload-ingest-{os.path.basename(file_path)}",
        daemon=True,
    )
    thread.start()


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------

@router.post("")
async def upload_files(
    files: List[UploadFile] = File(..., description="One or more files (or a ZIP archive)"),
):
    """Upload files directly for ingestion — no folder watching required.

    Saves each file to a timestamped directory, then queues ingestion in a
    background thread so the response returns immediately.

    Returns per-file status:
      ``queued``   — saved and ingestion started in background
      ``zip_extracted`` — ZIP was unpacked; member files are being ingested
      ``rejected`` — unsupported type or exceeds size limit
    """
    from app.main import get_pipeline
    pipeline = get_pipeline()
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Ingestion pipeline is not ready — is the server still starting up?",
        )

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    slot_dir = _make_slot()
    results: List[dict] = []
    queued = 0

    for upload in files:
        filename = upload.filename or "unnamed"

        # --- Size check (stream-limited read) ---
        content = await upload.read(_MAX_FILE_SIZE_BYTES + 1)
        if len(content) > _MAX_FILE_SIZE_BYTES:
            results.append({
                "file": filename,
                "status": "rejected",
                "reason": f"Exceeds {_MAX_FILE_SIZE_MB} MB limit",
            })
            continue

        ext = _ext(filename)

        # --- ZIP: extract and ingest each supported member ---
        if ext == ".zip":
            dest = _unique_dest(slot_dir, filename)
            with open(dest, "wb") as f:
                f.write(content)

            members = _extract_zip(dest, slot_dir)
            if not members:
                results.append({
                    "file": filename,
                    "status": "rejected",
                    "reason": "ZIP contained no supported files",
                })
                continue

            for member_path in members:
                _run_ingestion(member_path, pipeline)
                queued += 1

            results.append({
                "file": filename,
                "status": "zip_extracted",
                "extracted": [os.path.basename(m) for m in members],
                "queued": len(members),
            })
            continue

        # --- Unsupported type ---
        if not _is_supported(filename):
            results.append({
                "file": filename,
                "status": "rejected",
                "reason": f"Unsupported file type: {ext or '(none)'}",
            })
            continue

        # --- Supported file: save + queue ---
        dest = _unique_dest(slot_dir, filename)
        with open(dest, "wb") as f:
            f.write(content)

        _run_ingestion(dest, pipeline)
        queued += 1
        # Return the saved absolute path so the client can attach this file as
        # context for the current chat session.
        results.append({"file": filename, "status": "queued", "path": dest})

    rejected = sum(1 for r in results if r["status"] == "rejected")

    return JSONResponse({
        "upload_dir": slot_dir,
        "total_files": len(results),
        "queued": queued,
        "rejected": rejected,
        "results": results,
    })
