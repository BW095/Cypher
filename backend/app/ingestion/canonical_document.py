from typing import List, Dict, Any, Literal
from pydantic import BaseModel, Field


# Domains the extraction pipeline can handle.
DocDomain = Literal["industrial", "government"]

# Fine-grained government document categories; "general" covers industrial
# and any unrecognised document that falls through the classifier.
DocCategory = Literal["invoice", "contract", "certificate", "form", "general"]


class CanonicalDocument(BaseModel):
    file_path: str
    file_type: str
    text: str = ""
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    images: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)

    # Set by DocumentClassifier during ingestion; drives prompt selection in
    # EntityExtractor.  Defaults to industrial/general so existing documents
    # remain unaffected when re-ingestion is not triggered.
    doc_domain: DocDomain = "industrial"
    doc_category: DocCategory = "general"