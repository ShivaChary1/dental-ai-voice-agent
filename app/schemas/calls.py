import uuid
from datetime import datetime

from pydantic import BaseModel


class CallTurnOut(BaseModel):
    id: uuid.UUID
    turn_index: int
    role: str
    text: str
    stt_ms: int | None = None
    llm_ms: int | None = None
    tool_ms: int | None = None
    tts_first_byte_ms: int | None = None
    total_ms: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class CallSessionOut(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    room_name: str
    caller_id: str | None = None
    patient_id: uuid.UUID | None = None
    language: str
    status: str
    outcome: str | None = None
    started_at: datetime
    ended_at: datetime | None = None

    class Config:
        from_attributes = True


class CallSessionDetail(CallSessionOut):
    turns: list[CallTurnOut] = []


class CallLatencySummary(BaseModel):
    call_session_id: uuid.UUID
    turn_count: int
    avg_total_ms: float | None
    p50_total_ms: float | None
    p95_total_ms: float | None
    avg_stt_ms: float | None
    avg_llm_ms: float | None
    avg_tts_first_byte_ms: float | None
