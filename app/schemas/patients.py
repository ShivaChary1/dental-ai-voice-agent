import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    name: str
    phone: str = Field(pattern=r"^\+?[0-9]{7,15}$")
    dob: date | None = None
    preferred_language: str = "en-IN"
    email: str | None = None


class PatientUpdate(BaseModel):
    name: str | None = None
    dob: date | None = None
    preferred_language: str | None = None
    email: str | None = None


class PatientOut(BaseModel):
    id: uuid.UUID
    clinic_id: uuid.UUID
    name: str
    phone: str
    dob: date | None = None
    preferred_language: str
    email: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
