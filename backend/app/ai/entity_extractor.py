import json
import re
import sys
import traceback
from typing import Dict, List, Tuple
from app.ingestion.canonical_document import CanonicalDocument


from app.ai.llm import LLMWrapper
from app.config import ExtractionConfig, ModelConfig
class EntityExtractor:
    def __init__(self):
        # Use the dedicated extraction model if one is configured; otherwise
        # fall back to the main chat model (unchanged behavior).
        extraction_path = ModelConfig.EXTRACTION_MODEL_PATH or None
        if extraction_path:
            print(f"[EntityExtractor] Using dedicated extraction model: {extraction_path}")
        self.llm = LLMWrapper(model_path=extraction_path)

        self.system_prompt = """You are an AI expert in industrial knowledge extraction for plants, factories, and engineering organisations.
From the provided text, extract the KEY entities and the explicit relationships between them to build a unified knowledge graph. Sources include maintenance reports, P&IDs, work orders, inspection records, manuals, compliance documents, and emails.

EXTRACTION DISCIPLINE (read this first — it governs everything below):
- Be SELECTIVE, not exhaustive. Extract only entities that carry real operational meaning — what an engineer would actually track. A short passage usually yields a HANDFUL of entities, not dozens.
- Do NOT create a separate entity for any of these: routine clock times or timestamps ("08:15", "13:10"); record/document identifiers such as work-order numbers ("WO-1004"), report/ticket/log numbers; generic words ("system", "data", "report", "issue", "reading"); or vague noun phrases.
- A record ID (e.g. WO-1004) is a reference to a record, not a physical thing. If a work order matters, capture it ONCE as a PROCEDURE by its subject (e.g. "Mechanical Seal Replacement"), never as a LOCATION and never as something another entity sits "in".
- Merge duplicates: the same real-world thing mentioned several times is ONE entity — reuse the same id.

Entity types (use EXACTLY these):
- EQUIPMENT: machines and assets. Keep tag numbers verbatim ("Pump P-101", "Boiler B-2").
- COMPONENT: parts of equipment (valves, bearings, seals, impellers).
- PROCESS_PARAMETER: measured/controlled variables WITH their value when given ("Discharge Pressure 12 bar", "Bearing Temperature 85°C").
- FAILURE: failure modes, defects, incidents, near-misses, root causes (leaks, overheating, vibration, trips).
- PROCEDURE: maintenance tasks, inspections, tests, SOPs, and work orders (captured by subject, not by number).
- REGULATION: standards and regulatory references (Factory Act, OISD, PESO, IS/ISO codes, environmental/quality norms).
- PERSONNEL: named people or specific roles ("Shift Engineer", "A. Kumar").
- MATERIAL: consumables, lubricants, chemicals, spares.
- LOCATION: real physical places only — plants, units, areas, sections. NOT records, NOT equipment.
- DATE: only operationally significant dates — a deadline, a scheduled inspection date, an incident date (normalize to YYYY-MM-DD when possible). NOT routine clock times or every timestamp in a log.

Relationship types (use EXACTLY these). Create a relationship ONLY when the text explicitly states or clearly implies it — never invent one just to connect things or make the graph denser:
- PART_OF: Component -> Equipment; Equipment -> Location.
- HAS_FAILURE: Equipment/Component -> Failure.
- REQUIRES: Equipment/Failure -> Procedure or Material.
- MEASURES: Process_Parameter -> Equipment/Component.
- GOVERNED_BY: Equipment/Procedure -> Regulation.
- RESPONSIBLE_FOR: Personnel -> Equipment/Procedure.
- LOCATED_IN: Equipment/Personnel -> Location  (the target MUST be a LOCATION entity).
- OCCURRED_ON: Failure/Procedure -> Date.
- RELATES_TO: generic association — use sparingly, only when nothing above fits.

Rules:
- id: lowercase snake_case, stable and derived from the name ("pump_p101", "bearing_temp_85c"). Reuse the SAME id when the same real-world thing appears twice.
- name: short canonical name; preserve equipment tags, standard numbers, and units exactly as written.
- description: a SHORT factual phrase grounded in the text — at most 12 words, no full sentences, never invent facts. Omit filler; capture only the defining detail (e.g. "feed water pump, 12 bar discharge").
- Every relationship's source_id and target_id MUST be ids present in your entities list, and MUST respect the stated direction and endpoint types (e.g. LOCATED_IN's target is a LOCATION).

Output ONLY a valid JSON object, no explanations, no markdown fences:
{
    "entities": [
        {"id": "unique_string_id", "name": "Entity Name", "type": "ENTITY_TYPE", "description": "Short description"}
    ],
    "relationships": [
        {"source_id": "id_of_source_entity", "target_id": "id_of_target_entity", "type": "RELATIONSHIP_TYPE"}
    ]
}"""

    def process_document(self, document: CanonicalDocument) -> CanonicalDocument:
        """
        Analyzes the document text, extracts entities/relationships, and appends them to the document.
        If the document is too long, we extract from the first 4000 characters to prevent LLM context overflow.
        """
        print(f"Extracting entities for: {document.file_path}")
        sys.stdout.flush()

        if not document.text:
            print("  Skipping entity extraction: no text content.")
            return document

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
                    system_prompt=self.system_prompt,
                    max_tokens=2048,
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

    # Canonical entity types (upper snake) the graph is built around.
    _KNOWN_TYPES = {
        "EQUIPMENT", "COMPONENT", "PROCESS_PARAMETER", "FAILURE", "PROCEDURE",
        "REGULATION", "PERSONNEL", "MATERIAL", "LOCATION", "DATE",
    }

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

        for ent in entities:
            name = (ent.get("name") or "").strip()
            norm = self._normalize_name(name)
            if not norm:
                continue  # unusable entity — skip
            etype = self._normalize_type(ent.get("type"))
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

        canon_rels = []
        seen_rels = set()
        for rel in relationships:
            src = old_to_canon.get(str(rel.get("source_id")))
            tgt = old_to_canon.get(str(rel.get("target_id")))
            if not src or not tgt or src == tgt:
                continue  # dangling or self-loop — drop
            rtype = self._normalize_type(rel.get("type")) if rel.get("type") else "RELATES_TO"
            key = (src, tgt, rtype)
            if key in seen_rels:
                continue
            seen_rels.add(key)
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