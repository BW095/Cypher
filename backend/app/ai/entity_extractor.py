import json
import os
import re
import sys
import traceback
from typing import Dict, List, Tuple
from app.ingestion.canonical_document import CanonicalDocument


from app.ai.llm import LLMWrapper
from app.config import ExtractionConfig, ModelConfig


class EntityExtractor:
    def __init__(self):
        # Use the dedicated (smaller, faster) extraction model when its file is
        # present; otherwise transparently fall back to the main chat model, so
        # a missing/incomplete download never breaks ingestion.
        extraction_path = ModelConfig.EXTRACTION_MODEL_PATH or None
        if extraction_path and not os.path.exists(extraction_path):
            print(f"[EntityExtractor] Extraction model not found at {extraction_path} "
                  f"— using the main model for extraction.")
            extraction_path = None
        if extraction_path:
            print(f"[EntityExtractor] Using dedicated extraction model: {extraction_path}")
        self.llm = LLMWrapper(model_path=extraction_path)

    # ------------------------------------------------------------------
    # System prompts — one per document category
    # ------------------------------------------------------------------

    # Default prompt for industrial documents (maintenance reports, P&IDs,
    # work orders, inspection records, manuals, compliance documents, emails).
    _INDUSTRIAL_PROMPT = """You are an AI expert in industrial knowledge extraction for plants, factories, and engineering organisations.
From the provided text, extract the KEY entities and the explicit relationships between them to build a unified knowledge graph. Sources include maintenance reports, P&IDs, work orders, inspection records, manuals, compliance documents, and emails.

EXTRACTION DISCIPLINE (read this first — it governs everything below):
- Be SELECTIVE, not exhaustive. Extract only entities that carry real operational meaning — what an engineer would actually track. A short passage usually yields a HANDFUL of entities, not dozens.
- Do NOT create a separate entity for any of these: routine clock times or timestamps ("08:15", "13:10"); generic words ("system", "data", "report", "issue", "reading"); or vague noun phrases.
- A record ID (e.g. WO-1004) is a cross-document reference — capture it as DOC_REFERENCE, not as any other type.
- Merge duplicates: the same real-world thing mentioned several times is ONE entity — reuse the same id.

Entity types (use EXACTLY these):
- EQUIPMENT: machines and assets. Keep tag numbers verbatim ("Pump P-101", "Boiler B-2").
- COMPONENT: parts of equipment (valves, bearings, seals, impellers).
- PROCESS_PARAMETER: measured/controlled variables WITH their value when given ("Discharge Pressure 12 bar", "Bearing Temperature 85°C").
- FAILURE: failure modes, defects, incidents, near-misses, root causes (leaks, overheating, vibration, trips).
- PROCEDURE: maintenance tasks, inspections, tests, SOPs (captured by subject, not by number).
- REGULATION: standards and regulatory references (Factory Act, OISD, PESO, IS/ISO codes).
- PERSONNEL: named people or specific roles ("Shift Engineer", "A. Kumar").
- MATERIAL: consumables, lubricants, chemicals, spares.
- LOCATION: real physical places only — plants, units, areas, sections.
- DATE: only operationally significant dates — deadline, scheduled inspection date, incident date (normalize to YYYY-MM-DD when possible).
- DOC_REFERENCE: any explicit reference to another document by its identifier number — work order numbers ("WO-1004"), purchase order numbers ("PO-2024-45"), invoice numbers ("INV-001"), contract numbers ("CTR-09"), certificate numbers, report IDs, permit numbers. Capture the identifier exactly as written. Use this ONLY for references to OTHER documents, not for this document itself.

Relationship types (use EXACTLY these). Create a relationship ONLY when the text explicitly states or clearly implies it:
- PART_OF: Component -> Equipment; Equipment -> Location.
- HAS_FAILURE: Equipment/Component -> Failure.
- REQUIRES: Equipment/Failure -> Procedure or Material.
- MEASURES: Process_Parameter -> Equipment/Component.
- GOVERNED_BY: Equipment/Procedure -> Regulation.
- RESPONSIBLE_FOR: Personnel -> Equipment/Procedure.
- LOCATED_IN: Equipment/Personnel -> Location.
- OCCURRED_ON: Failure/Procedure -> Date.
- REFERENCES: this document -> DOC_REFERENCE (use when the document explicitly cites another document by ID).
- RELATES_TO: generic association — use sparingly, only when nothing above fits.

Rules:
- id: lowercase snake_case, stable and derived from the name. Reuse the SAME id when the same real-world thing appears twice.
- name: short canonical name; preserve equipment tags, document identifiers, and units exactly as written.
- description: a SHORT factual phrase grounded in the text — at most 12 words. Omit filler; capture only the defining detail.
- Every relationship's source_id and target_id MUST be ids present in your entities list.

Output ONLY a valid JSON object, no explanations, no markdown fences:
{
    "entities": [
        {"id": "unique_string_id", "name": "Entity Name", "type": "ENTITY_TYPE", "description": "Short description"}
    ],
    "relationships": [
        {"source_id": "id_of_source_entity", "target_id": "id_of_target_entity", "type": "RELATIONSHIP_TYPE"}
    ]
}"""

    # Prompt for government invoices / bills / receipts.
    _INVOICE_PROMPT = """You are an AI expert in government and commercial document knowledge extraction.
From the provided invoice / bill / receipt text, extract the KEY entities and explicit relationships to build a knowledge graph.

EXTRACTION DISCIPLINE:
- Be SELECTIVE. Extract only entities with real financial or transactional meaning.
- Do NOT create entities for generic labels ("description", "item", "s.no."), column headers, or every repeated boilerplate line.
- Merge duplicates: same real-world thing mentioned several times is ONE entity — reuse the same id.

Entity types (use EXACTLY these):
- INVOICE_LINE_ITEM: individual goods or services listed on the invoice, including quantity and unit price when stated ("Office Chairs x10 @ ₹2,500").
- CONTRACT_PARTY: named buyer, seller, vendor, client, or organisation on the invoice ("ABC Supplies Pvt. Ltd.", "Ministry of Finance").
- AMOUNT: any monetary total or subtotal WITH currency ("₹1,25,000", "USD 5,000", "Total GST ₹22,500").
- DATE_DUE: payment due date, invoice date, delivery date (normalize to YYYY-MM-DD when possible).
- CERTIFICATE_ISSUER: authority that issued any referenced certificate or registration (GST authority, MSME, etc.).
- SIGNATORY: person or role who signed or authorised the invoice ("Authorised Signatory", "Chief Financial Officer").
- JURISDICTION: place of supply, state, or governing authority mentioned.
- REGULATION: tax acts, GST provisions, regulatory references cited on the invoice.
- PERSONNEL: named individuals (not roles) appearing on the document.
- DATE: dates other than due/payment dates (e.g. invoice date, dispatch date).
- DOC_REFERENCE: any explicit reference to another document by its identifier — Purchase Order number ("PO-2024-45"), Contract number ("CTR-09"), Work Order, Tender ID, Framework Agreement number, Certificate number. Capture the identifier exactly as written.

Relationship types (use EXACTLY these):
- PAYABLE_TO: AMOUNT -> CONTRACT_PARTY (who receives the payment).
- ISSUED_BY: document context -> CERTIFICATE_ISSUER (for any certificate numbers cited).
- SIGNED_BY: document context -> SIGNATORY.
- GOVERNED_BY: INVOICE_LINE_ITEM/document -> REGULATION.
- REFERENCES: this document -> DOC_REFERENCE (when this invoice explicitly references another document by ID).
- RELATES_TO: generic association — use sparingly.
- OCCURRED_ON: DATE_DUE or DATE events.

Rules:
- id: lowercase snake_case derived from the name. Reuse SAME id for the same real-world thing.
- name: short canonical name; preserve currency symbols and values exactly.
- description: SHORT factual phrase (≤12 words) grounded in the text. Never invent facts.
- Every relationship's source_id and target_id MUST appear in your entities list.

Output ONLY a valid JSON object, no explanations, no markdown fences:
{
    "entities": [
        {"id": "unique_string_id", "name": "Entity Name", "type": "ENTITY_TYPE", "description": "Short description"}
    ],
    "relationships": [
        {"source_id": "id_of_source_entity", "target_id": "id_of_target_entity", "type": "RELATIONSHIP_TYPE"}
    ]
}"""

    # Prompt for government contracts / agreements / MoUs.
    _CONTRACT_PROMPT = """You are an AI expert in government and legal document knowledge extraction.
From the provided contract / agreement / MoU text, extract the KEY entities and explicit relationships to build a knowledge graph.

EXTRACTION DISCIPLINE:
- Be SELECTIVE. Extract parties, obligations, amounts, key dates, jurisdiction, and signatories — not boilerplate preamble words.
- Do NOT create entities for generic legal phrases ("whereas", "hereof", "thereof").
- Merge duplicates: same real-world thing is ONE entity — reuse the same id.

Entity types (use EXACTLY these):
- CONTRACT_PARTY: named parties, companies, ministries, or individuals who are signatories or stakeholders.
- AMOUNT: monetary values, penalties, fees, deposits WITH currency.
- DATE_DUE: deadlines, completion dates, payment schedules, notice periods (normalize to YYYY-MM-DD when possible).
- SIGNATORY: person or designation authorised to sign.
- JURISDICTION: governing law, courts, arbitration seat, place of execution.
- REGULATION: laws, acts, clauses, standards referenced in the contract.
- PROCEDURE: defined processes, milestones, deliverables, or work scope items.
- PERSONNEL: named individuals (not generic roles) mentioned in the document.
- LOCATION: physical sites, project locations, addresses relevant to contract execution.
- DATE: dates other than deadlines (e.g. execution date, commencement date).
- DOC_REFERENCE: any explicit reference to another document by its identifier — Invoice number, Purchase Order number, Tender ID, Framework Agreement number, Certificate number, previous contract number. Capture the identifier exactly as written.

Relationship types (use EXACTLY these):
- SIGNED_BY: CONTRACT_PARTY or document -> SIGNATORY.
- GOVERNED_BY: contract/PROCEDURE -> REGULATION or JURISDICTION.
- PAYABLE_TO: AMOUNT -> CONTRACT_PARTY.
- OCCURRED_ON: PROCEDURE/DATE_DUE event -> DATE.
- LOCATED_IN: PROCEDURE/work -> LOCATION.
- RESPONSIBLE_FOR: CONTRACT_PARTY -> PROCEDURE.
- REFERENCES: this document -> DOC_REFERENCE (when this contract explicitly references another document by ID).
- RELATES_TO: generic association — use sparingly.

Rules:
- id: lowercase snake_case derived from the name. Reuse SAME id for the same real-world thing.
- name: short canonical name; preserve currency symbols, article numbers, clause references exactly.
- description: SHORT factual phrase (≤12 words) grounded in the text. Never invent facts.
- Every relationship's source_id and target_id MUST appear in your entities list.

Output ONLY a valid JSON object, no explanations, no markdown fences:
{
    "entities": [
        {"id": "unique_string_id", "name": "Entity Name", "type": "ENTITY_TYPE", "description": "Short description"}
    ],
    "relationships": [
        {"source_id": "id_of_source_entity", "target_id": "id_of_target_entity", "type": "RELATIONSHIP_TYPE"}
    ]
}"""

    # Prompt for government certificates / registrations / licenses / NOCs.
    _CERTIFICATE_PROMPT = """You are an AI expert in government certificate and regulatory document knowledge extraction.
From the provided certificate / registration / license / NOC text, extract the KEY entities and explicit relationships to build a knowledge graph.

EXTRACTION DISCIPLINE:
- Be SELECTIVE. Focus on: who issued it, who it was awarded to, what it certifies, validity period, and signatories.
- Do NOT create entities for generic boilerplate ("this is to certify that", "as per the provisions of").
- Merge duplicates: same real-world thing is ONE entity — reuse the same id.

⚠️ CRITICAL — EXPIRY / VALIDITY DATES (highest priority):
Any phrase that indicates when the certificate/license stops being valid MUST be extracted as a DATE_DUE entity.
These phrases always signal a DATE_DUE:
  "valid till …", "valid until …", "valid up to …", "valid through …",
  "expiry date …", "expires on …", "expiring on …",
  "renewal due …", "renewal date …", "next renewal …",
  "validity: …", "valid for … years/months from …".
Extract the exact date (normalize to YYYY-MM-DD when possible) and create a VALID_UNTIL relationship:
  (certificate entity / CONTRACT_PARTY) -[:VALID_UNTIL]-> (DATE_DUE entity)
Failure to extract these dates makes compliance checking impossible.

Entity types (use EXACTLY these):
- CERTIFICATE_ISSUER: authority, department, or body that issued the certificate ("Registrar of Companies", "Bureau of Indian Standards", "Municipal Corporation").
- CONTRACT_PARTY: entity or individual the certificate is awarded/issued to.
- SIGNATORY: person, designation, or role who signed/authenticated the certificate.
- DATE_DUE: ⚠️ validity expiry date, renewal due date, or any date the certificate ceases to be valid (normalize to YYYY-MM-DD when possible). This is the most important date on the document.
- JURISDICTION: state, district, governing authority, or area of validity.
- REGULATION: act, rule, section, or standard under which the certificate is issued.
- AMOUNT: any fee, penalty, or bond amount mentioned WITH currency.
- PERSONNEL: named individuals (inspectors, certifying officers) mentioned.
- DATE: issue date, inspection date, commencement date — dates that are NOT the expiry (YYYY-MM-DD when possible).
- LOCATION: physical address, plant site, registered office relevant to the certificate.
- DOC_REFERENCE: any explicit reference to another document by its identifier — certificate number, license number, application number, previous registration ID. Capture exactly as written.

Relationship types (use EXACTLY these):
- ISSUED_BY: certificate context -> CERTIFICATE_ISSUER.
- SIGNED_BY: certificate context -> SIGNATORY.
- GOVERNED_BY: certificate/certification -> REGULATION or JURISDICTION.
- VALID_UNTIL: ⚠️ (certificate holder / CERTIFICATE_ISSUER / CONTRACT_PARTY) -> DATE_DUE. ALWAYS create this when an expiry or renewal date is present.
- LOCATED_IN: CONTRACT_PARTY/PERSONNEL -> LOCATION.
- REFERENCES: this document -> DOC_REFERENCE.
- RELATES_TO: generic association — use sparingly.

Rules:
- id: lowercase snake_case derived from the name. Reuse SAME id for the same real-world thing.
- name: short canonical name; preserve certificate numbers, registration numbers, and dates exactly as written.
- description: SHORT factual phrase (≤12 words) grounded in the text. For DATE_DUE, include "expiry" or "renewal due" in the description so it is clear this is a validity deadline.
- Every relationship's source_id and target_id MUST appear in your entities list.

Output ONLY a valid JSON object, no explanations, no markdown fences:
{
    "entities": [
        {"id": "unique_string_id", "name": "Entity Name", "type": "ENTITY_TYPE", "description": "Short description"}
    ],
    "relationships": [
        {"source_id": "id_of_source_entity", "target_id": "id_of_target_entity", "type": "RELATIONSHIP_TYPE"}
    ]
}"""

    # Prompt for government application forms / challan / nomination forms.
    _FORM_PROMPT = """You are an AI expert in government form and application document knowledge extraction.
From the provided form / application / challan text, extract the KEY entities and explicit relationships to build a knowledge graph.

EXTRACTION DISCIPLINE:
- Be SELECTIVE. Focus on: labeled fields with values, declared amounts, jurisdiction, signatories, and referenced regulations.
- Do NOT create entities for empty form fields, column headers, or blank lines.
- Merge duplicates: same real-world thing is ONE entity — reuse the same id.

Entity types (use EXACTLY these):
- FORM_FIELD: a labeled field WITH its filled value ("Applicant Name: Ravi Kumar", "Date of Birth: 1985-06-15", "Annual Income: ₹3,50,000"). Only extract fields that have a non-empty value.
- CONTRACT_PARTY: named organisations, departments, or institutions referenced.
- SIGNATORY: person or designation who signs or declares on the form.
- JURISDICTION: taluk, district, state, or court referenced as governing authority.
- AMOUNT: any monetary value WITH currency declared on the form.
- DATE_DUE: submission deadline, validity date (normalize to YYYY-MM-DD when possible).
- REGULATION: act, rule, scheme, or government order the form pertains to.
- PERSONNEL: named individuals (not just roles) filling or approving the form.
- DATE: dates stated on the form other than deadlines (YYYY-MM-DD when possible).
- LOCATION: specific addresses, village, district, state written on the form.
- DOC_REFERENCE: any explicit reference to another document by its identifier — Application number, Certificate number, License number, Order number, previous form or registration ID. Capture the identifier exactly as written.

Relationship types (use EXACTLY these):
- SIGNED_BY: form context -> SIGNATORY.
- GOVERNED_BY: form/FORM_FIELD -> REGULATION or JURISDICTION.
- PAYABLE_TO: AMOUNT -> CONTRACT_PARTY.
- LOCATED_IN: PERSONNEL/CONTRACT_PARTY -> LOCATION.
- REFERENCES: this document -> DOC_REFERENCE (when this form explicitly references another document by ID).
- RELATES_TO: generic association — use sparingly.
- OCCURRED_ON: DATE_DUE or DATE events.

Rules:
- id: lowercase snake_case derived from the field label and value. Reuse SAME id for the same real-world thing.
- name: "FieldLabel: Value" for FORM_FIELD; short canonical name for other types.
- description: SHORT factual phrase (≤12 words) grounded in the text. Never invent facts.
- Every relationship's source_id and target_id MUST appear in your entities list.

Output ONLY a valid JSON object, no explanations, no markdown fences:
{
    "entities": [
        {"id": "unique_string_id", "name": "Entity Name", "type": "ENTITY_TYPE", "description": "Short description"}
    ],
    "relationships": [
        {"source_id": "id_of_source_entity", "target_id": "id_of_target_entity", "type": "RELATIONSHIP_TYPE"}
    ]
}"""

    # ------------------------------------------------------------------
    # Entity type vocabulary
    # ------------------------------------------------------------------

    # Industrial entity types (existing).
    _INDUSTRIAL_TYPES = {
        "EQUIPMENT", "COMPONENT", "PROCESS_PARAMETER", "FAILURE", "PROCEDURE",
        "REGULATION", "PERSONNEL", "MATERIAL", "LOCATION", "DATE",
    }

    # Government-specific entity types added for this pipeline extension.
    _GOVERNMENT_TYPES = {
        "INVOICE_LINE_ITEM", "CONTRACT_PARTY", "AMOUNT", "DATE_DUE",
        "CERTIFICATE_ISSUER", "FORM_FIELD", "SIGNATORY", "JURISDICTION",
    }

    # Cross-document reference — used by the Document Entanglement Graph.
    # Every prompt instructs the LLM to extract these as DOC_REFERENCE.
    _ENTANGLEMENT_TYPES = {"DOC_REFERENCE"}

    # Union — all types accepted by the canonicaliser.
    _KNOWN_TYPES = _INDUSTRIAL_TYPES | _GOVERNMENT_TYPES | _ENTANGLEMENT_TYPES

    # ------------------------------------------------------------------
    # Prompt router
    # ------------------------------------------------------------------

    _PROMPT_MAP: Dict[str, str] = {}  # filled lazily in __init__

    def __init__(self):
        # Use the dedicated (smaller, faster) extraction model when its file is
        # present; otherwise transparently fall back to the main chat model, so
        # a missing/incomplete download never breaks ingestion.
        extraction_path = ModelConfig.EXTRACTION_MODEL_PATH or None
        if extraction_path and not os.path.exists(extraction_path):
            print(f"[EntityExtractor] Extraction model not found at {extraction_path} "
                  f"— using the main model for extraction.")
            extraction_path = None
        if extraction_path:
            print(f"[EntityExtractor] Using dedicated extraction model: {extraction_path}")
        self.llm = LLMWrapper(model_path=extraction_path)

        # Map doc_category → system prompt.
        self._PROMPT_MAP = {
            "general":     self._INDUSTRIAL_PROMPT,
            "invoice":     self._INVOICE_PROMPT,
            "contract":    self._CONTRACT_PROMPT,
            "certificate": self._CERTIFICATE_PROMPT,
            "form":        self._FORM_PROMPT,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_document(self, document: CanonicalDocument) -> CanonicalDocument:
        """
        Analyzes the document text, extracts entities/relationships, and appends them to the document.
        Routes to the correct extraction prompt based on the document's detected category
        (set by DocumentClassifier before this step).
        """
        print(f"Extracting entities for: {document.file_path}")
        sys.stdout.flush()

        if not document.text:
            print("  Skipping entity extraction: no text content.")
            return document

        # Select the prompt for this document's category.
        system_prompt = self._PROMPT_MAP.get(document.doc_category, self._INDUSTRIAL_PROMPT)
        print(f"  Using '{document.doc_category}' extraction prompt "
              f"(domain: {document.doc_domain})")
        sys.stdout.flush()

        # Window over the WHOLE document, not just the first 2000 chars, so
        # entities deep inside long manuals/reports are captured. Each window
        # is kept small enough that its entity-JSON output fits in max_tokens;
        # results are merged and canonicalized once at the end.
        windows = self._make_windows(
            document.text,
            size=ExtractionConfig.WINDOW_CHARS,
            overlap=ExtractionConfig.WINDOW_OVERLAP,
            max_windows=ExtractionConfig.MAX_WINDOWS,
        )
        print(f"  Extracting over {len(windows)} window(s) of {document.file_path}")
        sys.stdout.flush()

        raw_entities: List[Dict] = []
        raw_rels: List[Dict] = []
        for idx, window in enumerate(windows):
            try:
                raw_response = self.llm.generate(
                    prompt=f"TEXT TO ANALYZE:\n{window}",
                    system_prompt=system_prompt,
                    max_tokens=ExtractionConfig.MAX_TOKENS,
                )
                if not raw_response:
                    print(f"    Window {idx + 1}: empty LLM response — skipping.")
                    continue
                ents, rels = self._parse_json_response(raw_response)
                raw_entities.extend(ents)
                raw_rels.extend(rels)
            except Exception as e:
                print(f"    Window {idx + 1}: extraction failed ({e})")
                traceback.print_exc()
                sys.stdout.flush()

        # Resolve everything to deterministic canonical ids so the same
        # real-world thing (e.g. "Pump P-101") merges across windows AND across
        # documents in Neo4j instead of fragmenting into islands.
        entities, relationships = self._canonicalize(raw_entities, raw_rels)
        document.entities.extend(entities)
        document.relationships.extend(relationships)
        print(f"  Extracted {len(entities)} entities and {len(relationships)} "
              f"relationships (merged from {len(windows)} window(s)).")
        sys.stdout.flush()

        return document

    # ------------------------------------------------------------------
    # Text windowing
    # ------------------------------------------------------------------

    @staticmethod
    def _make_windows(text: str, size: int, overlap: int, max_windows: int) -> List[str]:
        """Slice text into overlapping windows, breaking on whitespace so we
        don't cut words. Capped at max_windows to bound LLM cost on huge files."""
        text = text.strip()
        if not text:
            return []
        if len(text) <= size:
            return [text]

        windows = []
        start = 0
        step = max(1, size - overlap)
        while start < len(text) and len(windows) < max_windows:
            end = min(start + size, len(text))
            # Extend to the next whitespace so we don't split a word/tag.
            if end < len(text):
                nxt = text.find(" ", end)
                end = nxt if nxt != -1 and nxt - end < 40 else end
            windows.append(text[start:end].strip())
            start += step
        return windows

    # ------------------------------------------------------------------
    # Cross-document entity resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize an entity name for stable matching.

        Collapses case, whitespace and punctuation, and canonicalizes tag
        numbers so 'Pump P-101', 'pump  p101' and 'PUMP P 101' all map to the
        same key. Returns '' for empty/garbage names.
        """
        if not name:
            return ""
        s = name.strip().lower()
        # Canonicalize equipment tags: letter-group + separators + digit-group
        # -> "<letters><digits>" (e.g. "p-101" / "p 101" -> "p101").
        s = re.sub(r'\b([a-z]{1,4})[\s\-_]*(\d{1,5})\b', r'\1\2', s)
        # Drop remaining punctuation, collapse whitespace.
        s = re.sub(r'[^a-z0-9\s]', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    @classmethod
    def _normalize_type(cls, etype: str) -> str:
        if not etype:
            return "UNKNOWN"
        t = etype.strip().upper().replace(" ", "_").replace("-", "_")
        return t if t in cls._KNOWN_TYPES else t or "UNKNOWN"

    def _canonicalize(self, entities: List[Dict], relationships: List[Dict]
                      ) -> Tuple[List[Dict], List[Dict]]:
        """Rewrite entity ids to canonical `type:normalized_name` keys and
        remap relationship endpoints through the same mapping.

        Deduplicates entities that collapse to the same key (keeping the
        richest description) and drops relationships whose endpoints don't
        resolve to a real entity.
        """
        old_to_canon: Dict[str, str] = {}
        merged: Dict[str, Dict] = {}

        dropped_types: Dict[str, int] = {}
        for ent in entities:
            name = (ent.get("name") or "").strip()
            norm = self._normalize_name(name)
            if not norm:
                continue  # unusable entity — skip
            etype = self._normalize_type(ent.get("type"))
            # Guardrail: keep only the known entity vocabulary. Smaller models
            # occasionally invent types (e.g. "REPORT") that the prompt says to
            # skip; dropping them keeps the graph consistent with the type
            # palette instead of scattering Unknown-coloured noise nodes.
            if etype not in self._KNOWN_TYPES:
                dropped_types[etype] = dropped_types.get(etype, 0) + 1
                continue
            canon_id = f"{etype.lower()}:{norm}".replace(" ", "_")

            old_id = ent.get("id")
            if old_id is not None:
                old_to_canon[str(old_id)] = canon_id

            desc = (ent.get("description") or "").strip()
            if canon_id not in merged:
                merged[canon_id] = {
                    "id": canon_id, "name": name, "type": etype, "description": desc,
                }
            else:
                # Same entity seen again — keep the longer description.
                if len(desc) > len(merged[canon_id]["description"]):
                    merged[canon_id]["description"] = desc

        if dropped_types:
            print(f"  Dropped {sum(dropped_types.values())} entity(ies) with "
                  f"out-of-vocabulary types: {dropped_types}")

        canon_rels = []
        seen_rels = set()

        # Relationships that are truly symmetric — we deduplicate both directions
        # so two windows that extract (A→B) and (B→A) for the same RELATES_TO
        # edge don't both survive into Neo4j.
        _SYMMETRIC = {"RELATES_TO", "REFERENCES"}

        # Fix 3 — PAYABLE_TO direction.
        # Correct semantic: AMOUNT -[:PAYABLE_TO]-> CONTRACT_PARTY
        # (the payment goes FROM the amount TO the recipient).
        # The LLM frequently gets this backwards for vendor→government flows.
        # Correction: if source is a CONTRACT_PARTY and target is an AMOUNT, flip.
        def _maybe_fix_direction(src_id: str, tgt_id: str, rtype: str):
            if rtype != "PAYABLE_TO":
                return src_id, tgt_id
            src_ent = merged.get(src_id, {})
            tgt_ent = merged.get(tgt_id, {})
            src_type = src_ent.get("type", "")
            tgt_type = tgt_ent.get("type", "")
            # If source is a party (not an amount) and target is an amount → flip
            if src_type == "CONTRACT_PARTY" and tgt_type == "AMOUNT":
                return tgt_id, src_id
            # If source is an amount and target is a party → correct already
            return src_id, tgt_id

        for rel in relationships:
            src = old_to_canon.get(str(rel.get("source_id")))
            tgt = old_to_canon.get(str(rel.get("target_id")))
            if not src or not tgt or src == tgt:
                continue  # dangling or self-loop — drop
            rtype = self._normalize_type(rel.get("type")) if rel.get("type") else "RELATES_TO"

            # Apply direction correction before deduplication check
            src, tgt = _maybe_fix_direction(src, tgt, rtype)

            key = (src, tgt, rtype)
            # Fix 1 — for symmetric types, treat (A,B,T) and (B,A,T) as the same edge
            undirected_key = (min(src, tgt), max(src, tgt), rtype) if rtype in _SYMMETRIC else key
            if undirected_key in seen_rels:
                continue
            seen_rels.add(undirected_key)
            canon_rels.append({"source_id": src, "target_id": tgt, "type": rtype})

        return list(merged.values()), canon_rels

    def _parse_json_response(self, response: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Safely strips thinking tags, markdown formatting, and parses the JSON string.
        Handles truncated JSON from max_tokens cutoff by extracting complete entities.
        """
        # Strip Qwen3 <think>...</think> blocks if present
        cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

        # Attempt 1: Direct JSON parse
        try:
            data = json.loads(cleaned)
            return data.get("entities", []), data.get("relationships", [])
        except json.JSONDecodeError:
            pass

        # Attempt 2: Extract from markdown ```json ... ``` blocks
        try:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
                return data.get("entities", []), data.get("relationships", [])
        except Exception as e:
            print(f"  Regex JSON extraction failed: {e}")

        # Attempt 3: Recover from truncated JSON (max_tokens cutoff).
        # Extract individual entity/relationship objects that are complete.
        print("  Attempting truncated JSON recovery...")
        entities = self._extract_complete_objects(cleaned, "entities")
        relationships = self._extract_complete_objects(cleaned, "relationships")
        if entities or relationships:
            print(f"  Recovered {len(entities)} entities and {len(relationships)} relationships from truncated JSON.")
            return entities, relationships

        print(f"  Warning: Could not parse LLM output. Raw (first 300 chars): {response[:300]}")
        return [], []

    def _extract_complete_objects(self, text: str, section: str) -> List[Dict]:
        """Extracts complete JSON objects from a potentially truncated array section."""
        results = []
        # Find the section array start
        pattern = rf'"{section}"\s*:\s*\['
        match = re.search(pattern, text)
        if not match:
            return results

        # Extract individual {...} objects after the array opening
        array_start = match.end()
        remaining = text[array_start:]

        # Find each complete object
        for obj_match in re.finditer(r'\{[^{}]*\}', remaining):
            try:
                obj = json.loads(obj_match.group(0))
                results.append(obj)
            except json.JSONDecodeError:
                continue

        return results