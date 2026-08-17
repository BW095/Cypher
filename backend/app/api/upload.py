"""
File Upload API
===============
POST /api/upload — accept multipart file uploads, save to a per-session
upload directory, and immediately run them through the ingestion pipeline.

Supports:
  - Individual files (any format the pipeline supports)
  - ZIP archives — extracted in place; each contained file is ingested

The upload directory is set via UPLOAD_DIR env var (default: backend/data/uploads).
Each upload lands in a timestamped sub-folder so file names never clash across
concurrent uploads.
"""

import os
import shutil
import tempfile
import zipfile
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

logger = logging.getLogger("cypher.api.upload")

router = APIRouter(prefix="/api/upload", tags=["Upload"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_UPLOAD_DIR = os.path.join(_BACKEND_DIR, "data", "uploads")
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", _DEFAULT_UPLOAD_DIR)

# File extensions the ingestion pipeline can handle (mirrors Dispatcher._EXTENSION_MAP)
_SUPPORTED_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp",
    ".mp4", ".mkv", ".avi", ".mov",
    ".mp3", ".wav", ".m4a", ".flac",
    ".xlsx", ".xls", ".csv",
    ".docx", ".doc", ".pptx", ".ppt", ".odt", ".html", ".txt",
    ".eml", ".msg",
}

_MAX_FILE_SIZE_MB = int(os.getenv("UPLOAD_MAX_MB", "100"))
_MAX_FILE_SIZE_BYTES = _MAX_FILE_SIZE_MB * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_supported(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in _SUPPORTED_EXTS


def _make_upload_slot() -> str:
    """Create and return a fresh timestamped directory under UPLOAD_DIR."""
    slot = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(UPLOAD_DIR, slot)
    os.makedirs(path, exist_ok=True)
    return path


def _ingest_file(file_path: str, pipeline) -> dict:
    """Run one file through the ingestion pipeline. Returns a result dict."""
    try:
        pipeline.process_file(file_path)
        return {"file": os.path.basename(file_path), "status": "queued"}
    except Exception as exc:
        logger.warning(f"[Upload] Ingestion failed for {file_path}: {exc}")
        return {"file": os.path.basename(file_path), "status": "failed", "error": str(exc)}


def _collect_files_from_zip(zip_path: str, dest_dir: str) -> List[str]:
    """Extract ZIP and return paths of all supported files inside it."""
    collected = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue  # skip directories
                if not _is_supported(member):
                    logger.debug(f"[Upload] Skipping unsupported ZIP member: {member}")
                    continue
                # Flatten path — avoid writing to arbitrary directories.
                safe_name = os.path.basename(member)
                if not safe_name:
                    continue
                dest = os.path.join(dest_dir, safe_name)
                # Handle name clashes within the ZIP.
                if os.path.exists(dest):
                    base, ext = os.path.splitext(safe_name)
                    dest = os.path.join(dest_dir, f"{base}_{len(collected)}{ext}")
                with zf.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                collected.append(dest)
    except zipfile.BadZipFile:
        logger.warning(f"[Upload] Bad ZIP file: {zip_path}")
    return collected


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------

@router.post("")
async def upload_files(
    files: List[UploadFile] = File(..., description="One or more files (or a ZIP archive)"),
):
    """Upload files directly for ingestion — no folder watching required.

    Accepts:
    - Any supported document type (PDF, DOCX, XLSX, images, audio, video…)
    - ZIP archives — all supported files inside are extracted and ingested

    Returns a per-file ingestion result list.
    """
    from app.main import get_pipeline
    pipeline = get_pipeline()
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Ingestion pipeline is not ready.")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    slot_dir = _make_upload_slot()

    results = []
    ingest_paths: List[str] = []

    for upload in files:
        filename = upload.filename or "unnamed"
        ext = os.path.splitext(filename.lower())[1]

        # Read content (bounded by size limit)
        content = await upload.read(_MAX_FILE_SIZE_BYTES + 1)
        if len(content) > _MAX_FILE_SIZE_BYTES:
            results.append({
                "file": filename,
                "status": "rejected",
                "error": f"File exceeds {_MAX_FILE_SIZE_MB} MB limit",
            })
            continue

        dest = os.path.join(slot_dir, filename)
        # Avoid clobbering if two uploads share a name
        if os.path.exists(dest):
            base, e = os.path.splitext(filename)
            dest = os.path.join(slot_dir, f"{base}_{len(results)}{e}")

        with open(dest, "wb") as f:
            f.write(content)

        if ext == ".zip":
            # Extract and collect all supported files inside.
            zip_files = _collect_files_from_zip(dest, slot_dir)
            if not zip_files:
                results.append({
                    "file": filename,
                    "status": "skipped",
                    "error": "ZIP contained no supported files",
                })
            else:
                results.append({
                    "file": filename,
                    "status": "zip_extracted",
                    "extracted": [os.path.basename(p) for p in zip_files],
                })
                ingest_paths.extend(zip_files)
        elif _is_supported(filename):
            ingest_paths.append(dest)
            results.append({"file": filename, "status": "accepted"})
        else:
            results.append({
                "file": filename,
                "status": "rejected",
                "error": f"Unsupported file type: {ext or '(none)'}",
            })

    # Ingest each accepted file through the pipeline.
    ingest_results = []
    for path in ingest_paths:
        ingest_results.append(_ingest_file(path, pipeline))

    # Merge ingest results back into the per-file result list.
    ingest_map = {r["file"]: r for r in ingest_results}
    final = []
    for r in results:
        if r["status"] == "accepted":
            ing = ingest_map.get(r["file"], {})
            r["status"] = ing.get("status", "queued")
            if "error" in ing:
                r["error"] = ing["error"]
        final.append(r)
    # Append any extracted ZIP file results
    for ing in ingest_results:
        f = ing["file"]
        if not any(r.get("file") == f for r in final):
            final.append(ing)

    total   = len(ingest_paths)
    queued  = sum(1 for r in ingest_results if r.get("status") == "queued")
    failed  = sum(1 for r in ingest_results if r.get("status") == "failed")

    return JSONResponse({
        "upload_dir": slot_dir,
        "total_files": total,
        "queued": queued,
        "failed": failed,
        "results": final,
    })
