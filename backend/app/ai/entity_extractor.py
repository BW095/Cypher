import json
import re
import sys
import traceback
from typing import Dict, List, Tuple
from app.ingestion.canonical_document import CanonicalDocument


from app.ai.llm import LLMWrapper
class EntityExtractor:
    def __init__(self):
        self.llm = LLMWrapper()

        self.system_prompt = """You are an AI expert in industrial knowledge extraction for plants, factories, and engineering organisations.
Extract entities and relationships from the provided text to build a unified knowledge graph. The sources include maintenance reports, P&IDs, work orders, inspection records, manuals, compliance documents, and emails.

Entity types (use EXACTLY these):
- EQUIPMENT: machines and assets. Keep tag numbers verbatim in the name (e.g. "Pump P-101", "Boiler B-2").
- COMPONENT: parts of equipment (valves, bearings, seals, impellers).
- PROCESS_PARAMETER: measured/controlled variables with values when given (e.g. "Discharge Pressure 12 bar", "Bearing Temperature 85°C").
- FAILURE: failure modes, defects, incidents, near-misses, root causes (leaks, overheating, vibration, trips).
- PROCEDURE: maintenance tasks, inspections, tests, SOPs, work orders.
- REGULATION: standards and regulatory references (Factory Act, OISD, PESO, IS/ISO codes, environmental norms, quality standards).
- PERSONNEL: people or roles (e.g. "Shift Engineer", "A. Kumar").
- MATERIAL: consumables, lubricants, chemicals, spares.
- LOCATION: plants, units, areas, sections.
- DATE: dates of events, inspections, or deadlines (normalize to YYYY-MM-DD when possible).

Relationship types (use EXACTLY these):
- PART_OF: Component -> Equipment; Equipment -> Location.
- HAS_FAILURE: Equipment/Component -> Failure.
- REQUIRES: Equipment/Failure -> Procedure or Material.
- MEASURES: Process_Parameter -> Equipment/Component.
- GOVERNED_BY: Equipment/Procedure -> Regulation.
- RESPONSIBLE_FOR: Personnel -> Equipment/Procedure.
- LOCATED_IN: Equipment/Personnel -> Location.
- OCCURRED_ON: Failure/Procedure -> Date.
- RELATES_TO: generic association (use only when nothing above fits).

Rules:
- id: lowercase snake_case, stable and derived from the name (e.g. "pump_p101", "bearing_temp_85c"). Reuse the SAME id when the same real-world thing appears twice.
- name: short canonical name; preserve equipment tags, standard numbers, and units exactly as written.
- description: one factual sentence grounded in the text — never invent facts. Ensure high accuracy.
- Every relationship's source_id and target_id MUST be ids from your entities list.
- Prefer fewer, high-confidence entities over many vague ones. Skip generic words ("system", "data", "report").

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

        # Keep input text short so the LLM output (entities JSON) fits within max_tokens.
        # Longer input = more entities = longer JSON output = higher truncation risk.
        text_to_analyze = document.text[:2000]

        try:
            raw_response = self.llm.generate(
                prompt=f"TEXT TO ANALYZE:\n{text_to_analyze}",
                system_prompt=self.system_prompt,
                max_tokens=2048
            )

            if not raw_response:
                print("  Warning: LLM returned empty response for entity extraction.")
                return document

            entities, relationships = self._parse_json_response(raw_response)
            document.entities.extend(entities)
            document.relationships.extend(relationships)
            print(f"  Extracted {len(entities)} entities and {len(relationships)} relationships.")
            sys.stdout.flush()

        except Exception as e:
            print(f"Failed to extract entities: {e}")
            traceback.print_exc()
            sys.stdout.flush()

        return document

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