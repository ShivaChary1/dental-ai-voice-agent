"""Appointment scheduling: availability, booking, reschedule, cancel.

All slot-claiming operations are written as conditional UPDATEs
(`WHERE status = 'available'`) so concurrent callers can never double-book
the same slot - the loser simply gets zero rows affected and is told the
slot is no longer available.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, AvailabilitySlot, Doctor, Patient, Service


class SchedulingError(Exception):
    pass


class SlotUnavailableError(SchedulingError):
    pass


class NotFoundError(SchedulingError):
    pass


async def get_or_create_patient(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    name: str,
    phone: str,
    preferred_language: str = "en-IN",
    dob: str | None = None,
) -> Patient:
    patient = await db.scalar(
        select(Patient).where(Patient.clinic_id == clinic_id, Patient.phone == phone)
    )
    if patient:
        # Keep the name fresh in case the caller gives a fuller name on a later call.
        if name and patient.name != name:
            patient.name = name
        return patient

    patient = Patient(
        clinic_id=clinic_id,
        name=name,
        phone=phone,
        preferred_language=preferred_language,
        dob=dob,
    )
    db.add(patient)
    await db.flush()
    return patient


async def check_availability(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    service_id: uuid.UUID,
    doctor_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 10,
) -> list[AvailabilitySlot]:
    start = start or datetime.utcnow()
    end = end or (start + timedelta(days=14))

    stmt = (
        select(AvailabilitySlot)
        .where(
            AvailabilitySlot.clinic_id == clinic_id,
            AvailabilitySlot.status == "available",
            AvailabilitySlot.start_time >= start,
            AvailabilitySlot.start_time <= end,
        )
        .order_by(AvailabilitySlot.start_time)
        .limit(limit)
    )
    if doctor_id:
        stmt = stmt.where(AvailabilitySlot.doctor_id == doctor_id)

    return list((await db.scalars(stmt)).all())


async def create_appointment(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    patient_id: uuid.UUID,
    doctor_id: uuid.UUID,
    service_id: uuid.UUID,
    slot_id: uuid.UUID,
    notes: str | None = None,
) -> Appointment:
    slot = await _claim_slot(db, clinic_id=clinic_id, slot_id=slot_id, doctor_id=doctor_id)

    service = await db.get(Service, service_id)
    if service is None or service.clinic_id != clinic_id:
        raise NotFoundError("Service not found for this clinic")

    appointment = Appointment(
        clinic_id=clinic_id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        service_id=service_id,
        slot_id=slot.id,
        start_time=slot.start_time,
        end_time=slot.end_time,
        status="scheduled",
        notes=notes,
        next_reminder_at=_first_reminder_time(slot.start_time),
        reminder_stage=0,
    )
    db.add(appointment)
    await db.flush()
    return appointment


async def find_appointments(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    phone: str,
    include_past: bool = False,
) -> list[Appointment]:
    stmt = (
        select(Appointment)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(Appointment.clinic_id == clinic_id, Patient.phone == phone)
        .order_by(Appointment.start_time.desc())
    )
    if not include_past:
        stmt = stmt.where(Appointment.status == "scheduled")
    return list((await db.scalars(stmt)).all())


async def reschedule_appointment(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    appointment_id: uuid.UUID,
    new_slot_id: uuid.UUID,
) -> Appointment:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None or appointment.clinic_id != clinic_id:
        raise NotFoundError("Appointment not found")
    if appointment.status != "scheduled":
        raise SchedulingError(f"Appointment is {appointment.status}, cannot reschedule")

    new_slot = await _claim_slot(
        db, clinic_id=clinic_id, slot_id=new_slot_id, doctor_id=appointment.doctor_id
    )

    # Release the old slot back into the pool.
    await db.execute(
        update(AvailabilitySlot)
        .where(AvailabilitySlot.id == appointment.slot_id)
        .values(status="available")
    )

    appointment.slot_id = new_slot.id
    appointment.start_time = new_slot.start_time
    appointment.end_time = new_slot.end_time
    appointment.next_reminder_at = _first_reminder_time(new_slot.start_time)
    appointment.reminder_stage = 0
    await db.flush()
    return appointment


async def cancel_appointment(
    db: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    appointment_id: uuid.UUID,
    reason: str | None = None,
) -> Appointment:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None or appointment.clinic_id != clinic_id:
        raise NotFoundError("Appointment not found")
    if appointment.status != "scheduled":
        raise SchedulingError(f"Appointment is already {appointment.status}")

    appointment.status = "cancelled"
    appointment.cancellation_reason = reason
    appointment.next_reminder_at = None

    await db.execute(
        update(AvailabilitySlot)
        .where(AvailabilitySlot.id == appointment.slot_id)
        .values(status="available")
    )

    await db.flush()
    return appointment


async def _claim_slot(
    db: AsyncSession, *, clinic_id: uuid.UUID, slot_id: uuid.UUID, doctor_id: uuid.UUID
) -> AvailabilitySlot:
    result = await db.execute(
        update(AvailabilitySlot)
        .where(
            AvailabilitySlot.id == slot_id,
            AvailabilitySlot.clinic_id == clinic_id,
            AvailabilitySlot.doctor_id == doctor_id,
            AvailabilitySlot.status == "available",
        )
        .values(status="booked")
        .returning(AvailabilitySlot)
    )
    slot = result.scalar_one_or_none()
    if slot is None:
        raise SlotUnavailableError("Selected slot is no longer available")
    return slot


def _first_reminder_time(appointment_start: datetime) -> datetime | None:
    """Default cadence: first reminder 48h before, falling back to "now" if
    the appointment is sooner than that. The reminder worker walks the
    remaining cadence stages from there."""
    candidate = appointment_start - timedelta(hours=48)
    now = datetime.utcnow()
    return candidate if candidate > now else now + timedelta(minutes=1)


async def get_doctor(db: AsyncSession, *, clinic_id: uuid.UUID, doctor_id: uuid.UUID) -> Doctor | None:
    doctor = await db.get(Doctor, doctor_id)
    if doctor is None or doctor.clinic_id != clinic_id:
        return None
    return doctor


async def list_services(db: AsyncSession, *, clinic_id: uuid.UUID) -> list[Service]:
    stmt = select(Service).where(Service.clinic_id == clinic_id, Service.active.is_(True))
    return list((await db.scalars(stmt)).all())


async def list_doctors(db: AsyncSession, *, clinic_id: uuid.UUID) -> list[Doctor]:
    stmt = select(Doctor).where(Doctor.clinic_id == clinic_id, Doctor.active.is_(True))
    return list((await db.scalars(stmt)).all())


async def resolve_service(db: AsyncSession, *, clinic_id: uuid.UUID, name: str) -> Service | None:
    stmt = (
        select(Service)
        .where(Service.clinic_id == clinic_id, Service.active.is_(True), Service.name.ilike(f"%{name}%"))
        .limit(1)
    )
    return await db.scalar(stmt)


async def resolve_doctor(db: AsyncSession, *, clinic_id: uuid.UUID, name: str) -> Doctor | None:
    stmt = (
        select(Doctor)
        .where(Doctor.clinic_id == clinic_id, Doctor.active.is_(True), Doctor.name.ilike(f"%{name}%"))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_appointment(db: AsyncSession, *, clinic_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment | None:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None or appointment.clinic_id != clinic_id:
        return None
    return appointment
