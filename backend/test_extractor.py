from app.ingestion.canonical_document import CanonicalDocument
from app.ai.entity_extractor import EntityExtractor
import sys

extractor = EntityExtractor()
doc = CanonicalDocument(file_path="test.txt", file_type="text", text="The main water pump (P-101) is experiencing a severe leak at the primary seal. It requires immediate maintenance to avoid overheating.")

doc = extractor.process_document(doc)

print("Entities:", doc.entities)
print("Relationships:", doc.relationships)
