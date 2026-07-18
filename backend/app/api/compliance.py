"""
Compliance API routes — regulatory coverage and gap detection.
"""

from fastapi import APIRouter, Query

from app.api.models import (
    ComplianceResponse, ComplianceSummary, ComplianceRegulation,
)

router = APIRouter(prefix="/api/compliance", tags=["Compliance"])


def get_deps():
    """Lazy import to avoid circular imports at module load time."""
    from app.main import get_neo4j, get_llm
    return get_neo4j(), get_llm()


# -------------------------------------------------------------------------
# GET /api/compliance/gaps — map regulations against procedures/evidence
# -------------------------------------------------------------------------
@router.get("/gaps", response_model=ComplianceResponse)
async def compliance_gaps(
    analyze: bool = Query(False, description="Add an LLM audit narrative (slower)"),
):
    """Analyze regulatory coverage and surface compliance gaps."""
    neo4j_db, llm = get_deps()

    from app.retrieval.compliance import ComplianceAnalyzer
    report = ComplianceAnalyzer(neo4j_db, llm).analyze(use_llm=analyze)

    return ComplianceResponse(
        summary=ComplianceSummary(**report.get("summary", {})),
        regulations=[ComplianceRegulation(**r) for r in report.get("regulations", [])],
        narrative=report.get("narrative"),
    )
