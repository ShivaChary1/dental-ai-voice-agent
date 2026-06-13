import uuid
from datetime import datetime

from pydantic import BaseModel


class KBDocumentCreate(BaseModel):
    title: str
    content: str
    language: str = "en-IN"
    source: str | None = None


class KBDocumentOut(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    title: str
    source: str | None = None
    language: str
    created_at: datetime

    class Config:
        from_attributes = True


class KBSearchRequest(BaseModel):
    query: str
    language: str = "en-IN"
    top_k: int = 4


class KBSearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    chunk_text: str
    score: float
