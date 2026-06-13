import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AuthedUser, DbSession
from app.db.models import Appointment
from app.schemas.appointments import (
    AppointmentCancel,
    AppointmentOut,
    AppointmentUpdate,
)
from app.services import scheduling_service
from app.services.scheduling_service import NotFoundError, SchedulingError, SlotUnavailableError

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("", response_model=list[AppointmentOut])
async def list_appointments(
    db: DbSession,
    user: AuthedUser,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> list[Appointment]:
    stmt = select(Appointment).where(Appointment.clinic_id == user.clinic_id)
    if status_filter:
        stmt = stmt.where(Appointment.status == status_filter)
    stmt = stmt.order_by(Appointment.start_time.desc()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


@router.get("/{appointment_id}", response_model=AppointmentOut)
async def get_appointment(appointment_id: uuid.UUID, db: DbSession, user: AuthedUser) -> Appointment:
    appointment = await scheduling_service.get_appointment(
        db, clinic_id=user.clinic_id, appointment_id=appointment_id
    )
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    return appointment


@router.patch("/{appointment_id}/reschedule", response_model=AppointmentOut)
async def reschedule(
    appointment_id: uuid.UUID, payload: AppointmentUpdate, db: DbSession, user: AuthedUser
) -> Appointment:
    try:
        appointment = await scheduling_service.reschedule_appointment(
            db, clinic_id=user.clinic_id, appointment_id=appointment_id, new_slot_id=payload.new_slot_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except SlotUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except SchedulingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await db.commit()
    await db.refresh(appointment)
    return appointment


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
async def cancel(
    appointment_id: uuid.UUID, payload: AppointmentCancel, db: DbSession, user: AuthedUser
) -> Appointment:
    try:
        appointment = await scheduling_service.cancel_appointment(
            db, clinic_id=user.clinic_id, appointment_id=appointment_id, reason=payload.reason
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except SchedulingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await db.commit()
    await db.refresh(appointment)
    return appointment


@router.get("/availability/slots")
async def get_availability(
    db: DbSession,
    user: AuthedUser,
    service_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    limit: int = Query(default=20, le=100),
):
    slots = await scheduling_service.check_availability(
        db, clinic_id=user.clinic_id, service_id=service_id, doctor_id=doctor_id, limit=limit
    )
    return [
        {
            "id": s.id,
            "doctor_id": s.doctor_id,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "status": s.status,
        }
        for s in slots
    ]
