import uuid
from datetime import datetime

from pydantic import BaseModel


class ReminderOut(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    appointment_id: uuid.UUID
    channel: str
    scheduled_at: datetime
    sent_at: datetime | None = None
    status: str
    attempt_count: int
    message: str | None = None
    error: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class MetricsOverview(BaseModel):
    period_days: int
    total_calls: int
    bookings: int
    reschedules: int
    cancellations: int
    faq_only: int
    escalated: int
    booking_conversion_rate: float
    escalation_rate: float
    language_breakdown: dict[str, int]
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    pending_reminders: int
