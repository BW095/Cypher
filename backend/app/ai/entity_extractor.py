import json
import re
import traceback
from typing import Dict, List, Tuple
from app.ingestion.canonical_document import CanonicalDocument


from app.ai.llm import LLMWrapper

class EntityExtractor:
    def __init__(self):
        self.llm = LLMWrapper()

        self.system_prompt = """
        You are an AI expert in industrial knowledge extraction.
        Your task is to extract entities and relationships from the provided industrial text.

        Focus on the following entity types:
        - EQUIPMENT (e.g., pumps, motors, compressors)
        - COMPONENT (e.g., valves, bearings, seals)
        - FAILURE (e.g., leaks, overheating, vibration)
        - PROCEDURE (e.g., maintenance steps, inspections)
        - METRIC (e.g., temperature, pressure, voltage)

        Focus on the following relationship types:
        - PART_OF (Component is part of Equipment)
        - HAS_FAILURE (Equipment/Component experiences Failure)
        - REQUIRES (Equipment requires Procedure)
        - MEASURES (Metric measures Equipment/Component)
        - RELATES_TO (Generic association)

        You MUST output ONLY a valid JSON object with the following schema, and absolutely no additional text or explanations:
        {
            "entities": [
                {"id": "unique_string_id", "name": "Entity Name", "type": "ENTITY_TYPE", "description": "Short description"}
            ],
            "relationships": [
                {"source_id": "id_of_source_entity", "target_id": "id_of_target_entity", "type": "RELATIONSHIP_TYPE"}
            ]
        }
        """

    def process_document(self, document: CanonicalDocument) -> CanonicalDocument:
        """
        Analyzes the document text, extracts entities/relationships, and appends them to the document.
        If the document is too long, we extract from the first 4000 characters to prevent LLM context overflow.
        """
        print(f"Extracting entities for: {document.file_path}")

        if not document.text:
            return document

        # For a prototype, take a representative chunk of text if it's massive.
        # In a production app, you might iterate over chunks and merge the graphs.
        text_to_analyze = document.text[:4000]

        prompt = f"{self.system_prompt}\n\nTEXT TO ANALYZE:\n{text_to_analyze}"

        try:
            # Replaces the mock string!
            raw_response = self.llm.generate(
                prompt=f"TEXT TO ANALYZE:\n{text_to_analyze}",
                system_prompt=self.system_prompt
            )

            entities, relationships = self._parse_json_response(raw_response)
            document.entities.extend(entities)
            document.relationships.extend(relationships)

        except Exception as e:
            print(f"Failed to extract entities: {e}")

        return document

    def _parse_json_response(self, response: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Safely strips markdown formatting (like ```json ... ```) and parses the JSON string.
        """
        try:
            # Try parsing directly first
            data = json.loads(response)
            return data.get("entities", []), data.get("relationships", [])
        except json.JSONDecodeError:
            pass

        try:
            # Fallback: Extract JSON block using regex if the LLM added markdown formatting
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
                return data.get("entities", []), data.get("relationships", [])
        except Exception as e:
            print(f"Regex JSON extraction failed: {e}")

        print("Warning: Could not parse LLM output into JSON.")
        return [], []