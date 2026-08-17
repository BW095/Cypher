"""
Structured Data Extractor
=========================
Reads a document's entities from Neo4j (already populated by EntityExtractor
during ingestion) and maps them to typed, human-readable key-value fields
according to per-category templates.

This is a *read-only, post-ingestion* step — no LLM calls, no re-parsing.
It simply projects the graph nodes that already exist into a flat structured
record that can be served via the Field Extraction API or exported to
CSV / Excel / JSON.

Architecture
------------
- ``FieldTemplate`` — a dataclass describing one field: its display label,
  which entity types to look for, and an optional secondary filter on the
  entity name/description text.
- ``TEMPLATES`` — dict mapping ``doc_category`` → list[FieldTemplate].
- ``StructuredExtractor.extract(file_path, doc_category)`` — the main entry
  point; returns a ``StructuredRecord``.

Adding a new field
------------------
1. Add a ``FieldTemplate`` to the relevant category list in ``TEMPLATES``.
2. Set ``entity_types`` to the Neo4j entity types that carry the value.
3. Optionally add ``name_hints`` (substrings) to disambiguate when multiple
   entities of the same type exist (e.g. AMOUNT for "total" vs "subtotal").
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cypher.structured_extractor")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FieldTemplate:
    """Describes one output field in a structured record."""
    field_key: str              # JSON key in the output (snake_case)
    label: str                  # Human-readable label shown in UI / export header
    entity_types: List[str]     # Neo4j entity types to search (in priority order)
    multi: bool = False         # True → collect ALL matching values as a list
    name_hints: List[str] = field(default_factory=list)
    # If set, only entities whose name OR description contains one of these
    # substrings (case-insensitive) are considered for this field.


@dataclass
class StructuredRecord:
    """The structured extraction result for one document."""
    file_path: str
    file_name: str
    doc_category: str           # invoice | contract | certificate | form | general
    doc_domain: str             # industrial | government
    fields: Dict[str, Any]      # key → value (str) or list[str] for multi fields
    source_entities: List[Dict] # raw entity dicts from Neo4j (for debugging)


# ---------------------------------------------------------------------------
# Field templates per document category
# ---------------------------------------------------------------------------

_INVOICE_FIELDS: List[FieldTemplate] = [
    FieldTemplate("vendor_name",    "Vendor / Seller",       ["CONTRACT_PARTY"],       name_hints=["vendor", "seller", "from", "supplier", "by"]),
    FieldTemplate("buyer_name",     "Buyer / Bill To",       ["CONTRACT_PARTY"],       name_hints=["buyer", "bill to", "client", "to"]),
    FieldTemplate("invoice_number", "Invoice Number",        ["FORM_FIELD"],            name_hints=["invoice no", "invoice number", "inv", "irn"]),
    FieldTemplate("invoice_date",   "Invoice Date",          ["DATE"],                  name_hints=["invoice date", "date of invoice", "bill date"]),
    FieldTemplate("due_date",       "Payment Due Date",      ["DATE_DUE"],              ),
    FieldTemplate("total_amount",   "Total Amount",          ["AMOUNT"],                name_hints=["total", "grand total", "payable", "net amount"]),
    FieldTemplate("tax_amount",     "Tax / GST Amount",      ["AMOUNT"],                name_hints=["gst", "tax", "igst", "cgst", "sgst", "vat"]),
    FieldTemplate("gst_number",     "GSTIN",                 ["FORM_FIELD"],            name_hints=["gstin", "gst no", "gst number", "gst registration"]),
    FieldTemplate("line_items",     "Line Items",            ["INVOICE_LINE_ITEM"],     multi=True),
    FieldTemplate("currency",       "Currency",              ["AMOUNT"],                name_hints=["currency", "₹", "usd", "inr", "eur"]),
    FieldTemplate("signatory",      "Authorised Signatory",  ["SIGNATORY"],             ),
    FieldTemplate("jurisdiction",   "Place of Supply",       ["JURISDICTION"],          ),
]

_CONTRACT_FIELDS: List[FieldTemplate] = [
    FieldTemplate("party_1",        "Party 1",               ["CONTRACT_PARTY"],       name_hints=["first part", "party a", "client", "employer", "owner"]),
    FieldTemplate("party_2",        "Party 2",               ["CONTRACT_PARTY"],       name_hints=["second part", "party b", "contractor", "vendor", "consultant"]),
    FieldTemplate("all_parties",    "All Parties",           ["CONTRACT_PARTY"],       multi=True),
    FieldTemplate("contract_value", "Contract Value",        ["AMOUNT"],               name_hints=["contract value", "total value", "lump sum", "contract amount"]),
    FieldTemplate("performance_bond","Performance Bond",     ["AMOUNT"],               name_hints=["performance", "bond", "security", "retention"]),
    FieldTemplate("start_date",     "Commencement Date",     ["DATE"],                 name_hints=["commence", "start", "effective", "agreement date"]),
    FieldTemplate("end_date",       "Completion / End Date", ["DATE_DUE"],             name_hints=["complet", "end date", "expiry", "handover"]),
    FieldTemplate("jurisdiction",   "Governing Jurisdiction",["JURISDICTION"],          ),
    FieldTemplate("signatories",    "Signatories",           ["SIGNATORY"],            multi=True),
    FieldTemplate("scope_of_work",  "Scope / Key Deliverables",["PROCEDURE"],         multi=True),
    FieldTemplate("regulations",    "Referenced Regulations",["REGULATION"],           multi=True),
]

_CERTIFICATE_FIELDS: List[FieldTemplate] = [
    FieldTemplate("certificate_no", "Certificate Number",    ["FORM_FIELD"],           name_hints=["certificate no", "cert no", "reg no", "registration no", "number"]),
    FieldTemplate("issued_to",      "Issued To",             ["CONTRACT_PARTY"],       ),
    FieldTemplate("issuer",         "Issuing Authority",     ["CERTIFICATE_ISSUER"],   ),
    FieldTemplate("issue_date",     "Issue Date",            ["DATE"],                 name_hints=["issue date", "date of issue", "awarded", "granted"]),
    FieldTemplate("expiry_date",    "Expiry / Valid Until",  ["DATE_DUE"],             ),
    FieldTemplate("jurisdiction",   "Area of Validity",      ["JURISDICTION"],         ),
    FieldTemplate("signatory",      "Authorised Signatory",  ["SIGNATORY"],            ),
    FieldTemplate("regulations",    "Issued Under (Act/Rule)",["REGULATION"],          multi=True),
    FieldTemplate("fee_amount",     "Fee / Bond Amount",     ["AMOUNT"],               ),
]

_FORM_FIELDS: List[FieldTemplate] = [
    FieldTemplate("applicant_name", "Applicant Name",        ["FORM_FIELD", "PERSONNEL"], name_hints=["applicant name", "name of applicant", "full name", "name"]),
    FieldTemplate("application_no", "Application / Form No", ["FORM_FIELD"],           name_hints=["application no", "form no", "reference no", "challan no"]),
    FieldTemplate("submission_date","Date of Submission",    ["DATE", "DATE_DUE"],     name_hints=["submit", "application date", "date of"]),
    FieldTemplate("fee_amount",     "Fee / Challan Amount",  ["AMOUNT"],               name_hints=["fee", "challan", "amount", "payment"]),
    FieldTemplate("signatory",      "Declarant / Signatory", ["SIGNATORY"],            ),
    FieldTemplate("jurisdiction",   "Jurisdiction / District",["JURISDICTION"],        ),
    FieldTemplate("form_fields",    "All Filled Fields",     ["FORM_FIELD"],           multi=True),
    FieldTemplate("regulation",     "Scheme / Act",          ["REGULATION"],           ),
]

_INDUSTRIAL_FIELDS: List[FieldTemplate] = [
    FieldTemplate("equipment",      "Equipment",             ["EQUIPMENT"],            multi=True),
    FieldTemplate("failures",       "Failures / Defects",    ["FAILURE"],              multi=True),
    FieldTemplate("procedures",     "Procedures / Work Orders",["PROCEDURE"],          multi=True),
    FieldTemplate("regulations",    "Regulations / Standards",["REGULATION"],          multi=True),
    FieldTemplate("key_dates",      "Key Dates",             ["DATE"],                 multi=True),
    FieldTemplate("personnel",      "Personnel",             ["PERSONNEL"],            multi=True),
]

TEMPLATES: Dict[str, List[FieldTemplate]] = {
    "invoice":     _INVOICE_FIELDS,
    "contract":    _CONTRACT_FIELDS,
    "certificate": _CERTIFICATE_FIELDS,
    "form":        _FORM_FIELDS,
    "general":     _INDUSTRIAL_FIELDS,
}


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class StructuredExtractor:
    """Reads Neo4j entities for a document and maps them to structured fields.

    Stateless — all data is fetched live from Neo4j.  Inject a
    ``Neo4jStorage`` instance (the shared singleton from main.py).
    """

    def __init__(self, neo4j_storage):
        self.db = neo4j_storage

    def extract(self, file_path: str, doc_category: str = "general",
                doc_domain: str = "industrial") -> StructuredRecord:
        """Build a ``StructuredRecord`` for ``file_path``.

        Fetches all entities linked to this document from Neo4j, then
        applies the appropriate field template to map entity values to
        named fields.
        """
        entities = self._fetch_entities(file_path)
        templates = TEMPLATES.get(doc_category, TEMPLATES["general"])
        fields_out: Dict[str, Any] = {}

        for tmpl in templates:
            matched = self._match_entities(entities, tmpl)
            if tmpl.multi:
                fields_out[tmpl.field_key] = [e["name"] for e in matched] if matched else []
            else:
                fields_out[tmpl.field_key] = matched[0]["name"] if matched else None

        return StructuredRecord(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            doc_category=doc_category,
            doc_domain=doc_domain,
            fields=fields_out,
            source_entities=entities,
        )

    def _fetch_entities(self, file_path: str) -> List[Dict]:
        """Return all Entity nodes linked to this Document via :MENTIONS."""
        try:
            records, _, _ = self.db.driver.execute_query(
                """
                MATCH (d:Document {path: $path})-[:MENTIONS]->(e:Entity)
                RETURN e.id AS id, e.name AS name, e.type AS type,
                       e.description AS description
                """,
                path=file_path,
                database_=self.db.database,
            )
            return [dict(r) for r in records]
        except Exception as exc:
            logger.error(f"[StructuredExtractor] Failed to fetch entities for {file_path}: {exc}")
            return []

    @staticmethod
    def _match_entities(entities: List[Dict], tmpl: FieldTemplate) -> List[Dict]:
        """Filter and score entities for a field template.

        Priority:
        1. Correct entity type (highest priority).
        2. If name_hints are given, entity name or description must contain
           at least one hint (case-insensitive).
        3. Preserve original order from Neo4j (insertion order = prominence).
        """
        type_set = {t.upper() for t in tmpl.entity_types}
        candidates = [e for e in entities if (e.get("type") or "").upper() in type_set]

        if not tmpl.name_hints or not candidates:
            return candidates

        # Filter by hints — an entity passes if its name OR description
        # contains at least one hint substring.
        hints_lower = [h.lower() for h in tmpl.name_hints]

        def _has_hint(e: Dict) -> bool:
            text = ((e.get("name") or "") + " " + (e.get("description") or "")).lower()
            return any(h in text for h in hints_lower)

        hinted = [e for e in candidates if _has_hint(e)]
        # Fall back to all type-matched candidates if no hints matched — better
        # than returning empty when the document uses non-standard phrasing.
        return hinted if hinted else candidates
