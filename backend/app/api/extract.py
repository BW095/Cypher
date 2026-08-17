"""
Structured Data Extraction & Export API
========================================

Endpoints
---------
GET  /api/extract/templates
    List all available field templates (one per document category).

GET  /api/extract/{doc_id}
    Return structured key-value fields for one ingested document.
    Query params:
      path (str)      — absolute file path of the tracked document
      category (str)  — override auto-detected category (optional)

GET  /api/extract/batch
    Return structured fields for all (or filtered) ingested documents.
    Query params:
      domain   (str)  — filter by domain ("industrial" | "government")
      category (str)  — filter by category ("invoice" | "contract" | ...)
      status   (str)  — filter by ingestion status (default "completed")

GET  /api/extract/export
    Download extracted fields as CSV, Excel, or JSON.
    Query params:
      format   (str)  — "csv" | "excel" | "json"  (default "json")
      domain   (str)  — same filters as /batch
      category (str)  — same filters as /batch
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.api.models import (
    StructuredFieldsResponse,
    BatchExtractionResponse,
    BatchExtractionItem,
    TemplateInfo,
    TemplateField,
)

logger = logging.getLogger("cypher.api.extract")

router = APIRouter(prefix="/api/extract", tags=["Structured Extraction"])


# ---------------------------------------------------------------------------
# Dependency helpers (lazy imports avoid circular-import issues at load time)
# ---------------------------------------------------------------------------

def _get_deps():
    from app.main import get_sqlite, get_neo4j
    return get_sqlite(), get_neo4j()


def _get_extractor():
    _, neo4j = _get_deps()
    if not neo4j:
        raise HTTPException(status_code=503, detail="Neo4j is unavailable — graph data cannot be read.")
    from app.extraction.structured_extractor import StructuredExtractor
    return StructuredExtractor(neo4j)


# ---------------------------------------------------------------------------
# Helper: resolve doc_category + doc_domain for a file_path
# ---------------------------------------------------------------------------

def _resolve_meta(file_path: str, sqlite) -> tuple[str, str]:
    """Try to read doc_domain / doc_category from Neo4j Document node metadata.

    Falls back to re-running the heuristic classifier on the filename alone
    if the document was ingested before the classifier was added.
    """
    try:
        _, neo4j = _get_deps()
        if neo4j:
            records, _, _ = neo4j.driver.execute_query(
                "MATCH (d:Document {path: $p}) RETURN d.doc_domain AS dom, d.doc_category AS cat",
                p=file_path, database_=neo4j.database,
            )
            if records:
                dom = records[0].get("dom") or "industrial"
                cat = records[0].get("cat") or "general"
                if dom and cat:
                    return cat, dom
    except Exception:
        pass

    # Fallback: classify from filename + empty text
    from app.ingestion.canonical_document import CanonicalDocument
    from app.ai.document_classifier import DocumentClassifier
    dummy = CanonicalDocument(file_path=file_path, file_type="")
    dummy = DocumentClassifier.classify(dummy)
    return dummy.doc_category, dummy.doc_domain


# ---------------------------------------------------------------------------
# GET /api/extract/templates
# ---------------------------------------------------------------------------

@router.get("/templates", response_model=list[TemplateInfo])
async def list_templates():
    """Return all available field extraction templates (one per document category).

    Useful for frontend form builders or for understanding what fields each
    document type will produce.
    """
    from app.extraction.structured_extractor import TEMPLATES
    result = []
    for category, tmpl_list in TEMPLATES.items():
        result.append(TemplateInfo(
            doc_category=category,
            fields=[
                TemplateField(
                    field_key=t.field_key,
                    label=t.label,
                    entity_types=t.entity_types,
                    multi=t.multi,
                    name_hints=t.name_hints,
                )
                for t in tmpl_list
            ],
        ))
    return result


# ---------------------------------------------------------------------------
# GET /api/extract   (single document — path as query param)
# ---------------------------------------------------------------------------

@router.get("", response_model=StructuredFieldsResponse)
async def extract_document(
    path: str = Query(..., description="Absolute path of the tracked document"),
    category: Optional[str] = Query(None, description="Override detected doc category"),
):
    """Return structured key-value fields for one ingested document.

    The fields returned depend on the document category:
    - **invoice** → vendor_name, invoice_number, total_amount, due_date, GST …
    - **contract** → party_1, party_2, contract_value, jurisdiction, signatories …
    - **certificate** → certificate_no, issued_to, issuer, expiry_date …
    - **form** → applicant_name, fee_amount, signatory, form_fields …
    - **general** (industrial) → equipment, failures, procedures …
    """
    sqlite, _ = _get_deps()

    # Security: only serve tracked documents.
    tracked = {d["file_path"] for d in sqlite.get_all_documents()} if sqlite else set()
    if path not in tracked:
        raise HTTPException(status_code=404, detail="File is not a tracked document.")

    doc_category, doc_domain = _resolve_meta(path, sqlite)
    if category:
        doc_category = category  # allow caller override

    extractor = _get_extractor()
    record = extractor.extract(path, doc_category=doc_category, doc_domain=doc_domain)

    return StructuredFieldsResponse(
        file_path=record.file_path,
        file_name=record.file_name,
        doc_domain=record.doc_domain,
        doc_category=record.doc_category,
        fields=record.fields,
        entity_count=len(record.source_entities),
    )


# ---------------------------------------------------------------------------
# GET /api/extract/batch
# ---------------------------------------------------------------------------

@router.get("/batch", response_model=BatchExtractionResponse)
async def extract_batch(
    domain: Optional[str] = Query(None, description="Filter by domain: industrial | government"),
    category: Optional[str] = Query(None, description="Filter by category: invoice | contract | certificate | form | general"),
    status: str = Query("completed", description="Filter by ingestion status"),
):
    """Return structured fields for all (or filtered) ingested documents.

    Applies per-document category templates so each document is extracted
    with the right fields for its type.  All results are returned in a single
    JSON payload; use ``/export`` for CSV or Excel download.
    """
    sqlite, _ = _get_deps()
    if not sqlite:
        raise HTTPException(status_code=503, detail="SQLite tracker is unavailable.")

    all_docs = sqlite.get_all_documents()
    docs = [d for d in all_docs if d.get("status") == status]

    extractor = _get_extractor()
    items = []

    for doc in docs:
        file_path = doc.get("file_path", "")
        if not file_path or not os.path.isfile(file_path):
            continue

        doc_category, doc_domain = _resolve_meta(file_path, sqlite)

        # Apply domain / category filters AFTER resolving meta.
        if domain and doc_domain != domain:
            continue
        if category and doc_category != category:
            continue

        try:
            record = extractor.extract(file_path, doc_category=doc_category, doc_domain=doc_domain)
            items.append(BatchExtractionItem(
                file_path=record.file_path,
                file_name=record.file_name,
                doc_domain=record.doc_domain,
                doc_category=record.doc_category,
                fields=record.fields,
            ))
        except Exception as exc:
            logger.warning(f"[extract_batch] Skipping {file_path}: {exc}")
            continue

    return BatchExtractionResponse(total=len(items), items=items)


# ---------------------------------------------------------------------------
# GET /api/extract/export
# ---------------------------------------------------------------------------

@router.get("/export")
async def export_extracted_fields(
    format: str = Query("json", description="Export format: json | csv | excel"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    category: Optional[str] = Query(None, description="Filter by category"),
    status: str = Query("completed", description="Filter by ingestion status"),
):
    """Download extracted structured fields as CSV, Excel, or JSON.

    - **json** — pretty-printed JSON array (one object per document)
    - **csv**  — UTF-8 CSV with BOM (opens correctly in Excel/LibreOffice)
    - **excel** — .xlsx workbook; one sheet per document category, styled headers

    The same domain/category filters as ``/batch`` apply.
    """
    from app.extraction.export import to_json, to_csv, to_excel
    from app.extraction.structured_extractor import StructuredExtractor

    sqlite, _ = _get_deps()
    if not sqlite:
        raise HTTPException(status_code=503, detail="SQLite tracker is unavailable.")

    all_docs = sqlite.get_all_documents()
    docs = [d for d in all_docs if d.get("status") == status]

    extractor = _get_extractor()
    records = []

    for doc in docs:
        file_path = doc.get("file_path", "")
        if not file_path or not os.path.isfile(file_path):
            continue
        doc_category, doc_domain = _resolve_meta(file_path, sqlite)
        if domain and doc_domain != domain:
            continue
        if category and doc_category != category:
            continue
        try:
            records.append(extractor.extract(file_path, doc_category=doc_category, doc_domain=doc_domain))
        except Exception as exc:
            logger.warning(f"[export] Skipping {file_path}: {exc}")

    fmt = format.lower().strip()
    if fmt == "csv":
        content, media_type, filename = to_csv(records)
    elif fmt in ("excel", "xlsx"):
        content, media_type, filename = to_excel(records)
    else:
        content, media_type, filename = to_json(records)

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )
