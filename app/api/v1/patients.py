import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AuthedUser, DbSession
from app.db.models import Patient
from app.schemas.patients import PatientCreate, PatientOut, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=list[PatientOut])
async def list_patients(
    db: DbSession,
    user: AuthedUser,
    phone: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> list[Patient]:
    stmt = select(Patient).where(Patient.clinic_id == user.clinic_id)
    if phone:
        stmt = stmt.where(Patient.phone == phone)
    stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(payload: PatientCreate, db: DbSession, user: AuthedUser) -> Patient:
    existing = await db.scalar(
        select(Patient).where(Patient.clinic_id == user.clinic_id, Patient.phone == payload.phone)
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "A patient with this phone number already exists")

    patient = Patient(clinic_id=user.clinic_id, **payload.model_dump())
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return patient


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(patient_id: uuid.UUID, db: DbSession, user: AuthedUser) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.clinic_id != user.clinic_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    return patient


@router.patch("/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: uuid.UUID, payload: PatientUpdate, db: DbSession, user: AuthedUser
) -> Patient:
    patient = await db.get(Patient, patient_id)
    if patient is None or patient.clinic_id != user.clinic_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)

    await db.commit()
    await db.refresh(patient)
    return patient
