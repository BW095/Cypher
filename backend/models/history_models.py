from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class SessionModel(BaseModel):
    session_id: str
    created_at: datetime

class MessageModel(BaseModel):
    role: str
    content: str
    timestamp: datetime

class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: List[MessageModel]
