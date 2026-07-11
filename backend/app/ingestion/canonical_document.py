from typing import List, Dict, Any
from pydantic import BaseModel, Field

class CanonicalDocument(BaseModel):
    file_path: str
    file_type: str
    text: str = ""
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    images: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)

import torch
print(torch.cuda.is_available())