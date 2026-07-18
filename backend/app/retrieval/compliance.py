"""
Compliance gap analysis.

Maps the REGULATION entities discovered during ingestion against the
procedures, equipment, and evidence documents they're linked to in the
knowledge graph, and classifies each regulation's coverage:

  * covered  — linked to at least one procedure AND backed by evidence docs
  * partial  — some linkage, but missing procedures or evidence
  * gap      — a regulation nobody's procedures or records connect to

This directly targets the "compliance gap detection accuracy" evaluation
criterion. It is graph-driven (fast, deterministic); an optional single LLM
pass produces an audit-style narrative over the compiled findings.
"""

import os
import sys
import html
from datetime import datetime

_PROCEDURE_TYPES = {"PROCEDURE"}
_ASSET_TYPES = {"EQUIPMENT", "COMPONENT"}


class ComplianceAnalyzer:
    def __init__(self, neo4j_db, llm=None):
        self.neo4j_db = neo4j_db
        self.llm = llm

    def analyze(self, use_llm: bool = False) -> dict:
        """Return a structured compliance report.

        {
          summary: {total, covered, partial, gaps},
          regulations: [{name, description, status, linked_procedures,
                         linked_equipment, evidence_documents, gap_reason}],
          narrative: str | None,
        }
        """
        if self.neo4j_db is None:
            return {"summary": self._summary([]), "regulations": [], "narrative": None}

        print("[Compliance] Scanning regulations in the knowledge graph...")
        sys.stdout.flush()

        regulations = self.neo4j_db.get_entities_by_type("REGULATION")
        findings = []

        for reg in regulations:
            neigh = self.neo4j_db.get_entity_neighborhood(reg.get("id", ""))
            neighbors = neigh["neighbors"]
            documents = neigh["documents"]

            procedures = [n for n in neighbors if (n.get("type") or "").upper() in _PROCEDURE_TYPES]
            equipment = [n for n in neighbors if (n.get("type") or "").upper() in _ASSET_TYPES]

            status, reason = self._classify(procedures, equipment, documents)
            findings.append({
                "name": reg.get("name", ""),
                "description": reg.get("description", ""),
                "status": status,
                "linked_procedures": [p.get("name", "") for p in procedures],
                "linked_equipment": [e.get("name", "") for e in equipment],
                "evidence_documents": [os.path.basename(d) for d in documents],
                "gap_reason": reason,
            })

        # Gaps first, then partial, then covered — most actionable at the top.
        order = {"gap": 0, "partial": 1, "covered": 2}
        findings.sort(key=lambda f: order.get(f["status"], 3))

        report = {
            "summary": self._summary(findings),
            "regulations": findings,
            "narrative": None,
        }

        if use_llm and self.llm and findings:
            report["narrative"] = self._narrate(findings)

        print(f"[Compliance] {report['summary']}")
        sys.stdout.flush()
        return report

    @staticmethod
    def _classify(procedures, equipment, documents):
        if not procedures and not equipment and not documents:
            return "gap", "No procedures, equipment, or records reference this regulation."
        if not procedures:
            return "partial", "Referenced in documents but not linked to any procedure or control."
        if not documents:
            return "partial", "Linked to procedures but no evidence document backs it."
        return "covered", ""

    @staticmethod
    def _summary(findings):
        return {
            "total": len(findings),
            "covered": sum(1 for f in findings if f["status"] == "covered"),
            "partial": sum(1 for f in findings if f["status"] == "partial"),
            "gaps": sum(1 for f in findings if f["status"] == "gap"),
        }

    def evidence_pack(self, regulation: str | None = None, use_llm: bool = False) -> dict:
        """Build the data for an audit evidence package.

        If `regulation` is given, restricts the report to that one regulation
        (case-insensitive). Returns the same shape as analyze(), filtered.
        """
        report = self.analyze(use_llm=use_llm)
        if regulation:
            reg_l = regulation.strip().lower()
            report["regulations"] = [
                r for r in report["regulations"]
                if r.get("name", "").lower() == reg_l
            ]
            report["summary"] = self._summary(report["regulations"])
        return report

    def _narrate(self, findings):
        """One LLM pass producing an auditor-style summary of the findings."""
        lines = []
        for f in findings:
            lines.append(
                f"- {f['name']} [{f['status'].upper()}]: "
                f"procedures={f['linked_procedures'] or 'none'}, "
                f"evidence={f['evidence_documents'] or 'none'}. {f['gap_reason']}"
            )
        findings_block = "\n".join(lines)
        system = (
            "You are a compliance auditor for an industrial plant. Given a list "
            "of regulations and their coverage status from the knowledge graph, "
            "write a concise audit summary: highlight the most serious gaps first, "
            "explain the operational/safety risk of each gap, and recommend the "
            "specific evidence or procedure needed to close it. Use only the data "
            "provided; do not invent regulations or documents."
        )
        prompt = f"Compliance coverage findings:\n{findings_block}\n\nWrite the audit summary."
        try:
            return self.llm.generate(prompt=prompt, system_prompt=system, max_tokens=800)
        except Exception as e:
            print(f"[Compliance] LLM narrative failed: {e}")
            return None


# ---------------------------------------------------------------------------
# Audit evidence package renderer (pure — no DB/LLM)
# ---------------------------------------------------------------------------

_STATUS_COLOR = {"covered": "#2e7d32", "partial": "#b8860b", "gap": "#c62828"}


def render_evidence_html(report: dict, title: str = "Compliance Evidence Package") -> str:
    """Render an analyze()/evidence_pack() report as a self-contained,
    printable HTML document (browser 'Print to PDF' produces the audit PDF)."""
    e = html.escape
    s = report.get("summary", {})
    regs = report.get("regulations", [])
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    def li_list(items):
        items = [i for i in items if i]
        if not items:
            return '<span class="none">None linked</span>'
        return "<ul>" + "".join(f"<li>{e(str(i))}</li>" for i in items) + "</ul>"

    cards = []
    for r in regs:
        status = r.get("status", "gap")
        color = _STATUS_COLOR.get(status, "#555")
        gap = (f'<div class="gap"><strong>Gap:</strong> {e(r.get("gap_reason",""))}</div>'
               if r.get("gap_reason") else "")
        cards.append(f"""
        <section class="card">
          <div class="card-head">
            <h2>{e(r.get('name',''))}</h2>
            <span class="badge" style="background:{color}">{e(status.upper())}</span>
          </div>
          {f'<p class="desc">{e(r.get("description",""))}</p>' if r.get('description') else ''}
          <div class="grid">
            <div><h3>Linked Procedures</h3>{li_list(r.get('linked_procedures', []))}</div>
            <div><h3>Linked Equipment</h3>{li_list(r.get('linked_equipment', []))}</div>
            <div><h3>Evidence Documents</h3>{li_list(r.get('evidence_documents', []))}</div>
          </div>
          {gap}
        </section>""")

    narrative = ""
    if report.get("narrative"):
        narrative = f'<section class="card narrative"><h2>Auditor Narrative</h2><pre>{e(report["narrative"])}</pre></section>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{e(title)}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; color:#1a1a1a;
         max-width: 900px; margin: 0 auto; padding: 40px 28px; }}
  header {{ border-bottom: 3px solid #e8a33d; padding-bottom: 16px; margin-bottom: 24px; }}
  h1 {{ margin: 0 0 4px; font-size: 24px; }}
  .meta {{ color:#666; font-size: 13px; }}
  .summary {{ display:flex; gap:14px; margin: 20px 0; flex-wrap:wrap; }}
  .summary div {{ border:1px solid #ddd; border-radius:8px; padding:10px 16px; text-align:center; }}
  .summary .n {{ font-size:22px; font-weight:700; }}
  .summary .l {{ font-size:12px; color:#666; text-transform:uppercase; letter-spacing:.05em; }}
  .card {{ border:1px solid #ddd; border-radius:10px; padding:18px 20px; margin-bottom:16px;
          page-break-inside: avoid; }}
  .card-head {{ display:flex; align-items:center; justify-content:space-between; }}
  .card-head h2 {{ margin:0; font-size:18px; }}
  .badge {{ color:#fff; font-size:12px; font-weight:700; padding:3px 10px; border-radius:20px; }}
  .desc {{ color:#444; margin:8px 0 12px; }}
  .grid {{ display:grid; grid-template-columns: repeat(3, 1fr); gap:16px; }}
  .grid h3 {{ font-size:12px; text-transform:uppercase; color:#888; letter-spacing:.05em; margin:0 0 6px; }}
  ul {{ margin:0; padding-left:18px; font-size:14px; }}
  .none {{ color:#c62828; font-size:13px; font-style:italic; }}
  .gap {{ margin-top:12px; padding:10px 12px; background:#fdf0f0; border-left:3px solid #c62828;
         border-radius:4px; font-size:14px; }}
  .narrative pre {{ white-space:pre-wrap; font-family:inherit; font-size:14px; line-height:1.5; }}
  @media print {{ body {{ padding: 0; }} }}
</style></head>
<body>
  <header>
    <h1>{e(title)}</h1>
    <div class="meta">Generated by Cypher · {e(generated)}</div>
  </header>
  <div class="summary">
    <div><div class="n">{s.get('total',0)}</div><div class="l">Regulations</div></div>
    <div><div class="n">{s.get('covered',0)}</div><div class="l">Covered</div></div>
    <div><div class="n">{s.get('partial',0)}</div><div class="l">Partial</div></div>
    <div><div class="n">{s.get('gaps',0)}</div><div class="l">Gaps</div></div>
  </div>
  {narrative}
  {''.join(cards) if cards else '<p>No regulations found in the knowledge graph.</p>'}
</body></html>"""
