import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AvailabilitySlotOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    status: str

    class Config:
        from_attributes = True


class AppointmentCreate(BaseModel):
    patient_name: str
    patient_phone: str = Field(pattern=r"^\+?[0-9]{7,15}$")
    patient_dob: str | None = None
    preferred_language: str = "en-IN"
    doctor_id: uuid.UUID
    service_id: uuid.UUID
    slot_id: uuid.UUID
    notes: str | None = None


class AppointmentUpdate(BaseModel):
    new_slot_id: uuid.UUID


class AppointmentCancel(BaseModel):
    reason: str | None = None


class AppointmentOut(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    doctor_id: uuid.UUID
    service_id: uuid.UUID
    slot_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    status: str
    notes: str | None = None
    cancellation_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
