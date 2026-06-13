"""LangChain tools exposed to the conversation agent.

Each tool is a thin, validated wrapper over `app.services.*`. Tools are
built per-call via `build_tools()` so they close over the request's DB
session, clinic id and language - the LLM never sees or controls those.
"""

import uuid

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import kb_service, scheduling_service
from app.services.scheduling_service import NotFoundError, SchedulingError, SlotUnavailableError

_DATE_FMT = "%Y-%m-%d %H:%M"


def _fmt_slot(slot) -> str:
    return f"slot_id={slot.id} | {slot.start_time.strftime(_DATE_FMT)} - {slot.end_time.strftime('%H:%M')}"


class SearchKBArgs(BaseModel):
    query: str = Field(description="The patient's question, in their own words.")


class CheckAvailabilityArgs(BaseModel):
    service_name: str = Field(description="Name of the service/treatment, e.g. 'cleaning', 'root canal'.")
    doctor_name: str | None = Field(default=None, description="Preferred doctor's name, if any.")
    date_from: str | None = Field(default=None, description="ISO date (YYYY-MM-DD) to start searching from. Defaults to today.")
    date_to: str | None = Field(default=None, description="ISO date (YYYY-MM-DD) to search until. Defaults to 14 days from date_from.")


class BookAppointmentArgs(BaseModel):
    patient_name: str = Field(description="Full name of the patient.")
    patient_phone: str = Field(description="Patient's phone number, confirmed by reading it back to them.")
    service_name: str = Field(description="Service/treatment name as discussed.")
    doctor_name: str | None = Field(default=None, description="Doctor's name, if the patient specified one.")
    slot_id: str = Field(description="The exact slot_id returned by check_availability that the patient agreed to.")
    notes: str | None = Field(default=None, description="Any extra notes from the patient (symptoms, requests).")


class FindAppointmentsArgs(BaseModel):
    patient_phone: str = Field(description="Phone number to look up appointments for, confirmed with the patient.")


class RescheduleAppointmentArgs(BaseModel):
    appointment_id: str = Field(description="The appointment_id from find_my_appointments.")
    new_slot_id: str = Field(description="The new slot_id from check_availability that the patient agreed to.")


class CancelAppointmentArgs(BaseModel):
    appointment_id: str = Field(description="The appointment_id from find_my_appointments.")
    reason: str | None = Field(default=None, description="Reason for cancellation, if the patient gave one.")


def build_tools(db: AsyncSession, *, clinic_id: uuid.UUID, language: str) -> list[StructuredTool]:
    async def search_clinic_kb(query: str) -> str:
        results = await kb_service.search_kb(db, clinic_id=clinic_id, query=query, language=language, top_k=4)
        if not results:
            results = await kb_service.search_kb(db, clinic_id=clinic_id, query=query, top_k=4)
        if not results:
            return "NO_RESULTS: nothing relevant found in the clinic knowledge base."
        return "\n---\n".join(f"[{r['title']}] {r['chunk_text']}" for r in results)

    async def check_availability(
        service_name: str,
        doctor_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> str:
        from datetime import datetime

        service = await scheduling_service.resolve_service(db, clinic_id=clinic_id, name=service_name)
        if service is None:
            services = await scheduling_service.list_services(db, clinic_id=clinic_id)
            names = ", ".join(s.name for s in services)
            return f"UNKNOWN_SERVICE: '{service_name}' not found. Available services: {names}"

        doctor_id = None
        if doctor_name:
            doctor = await scheduling_service.resolve_doctor(db, clinic_id=clinic_id, name=doctor_name)
            if doctor is None:
                doctors = await scheduling_service.list_doctors(db, clinic_id=clinic_id)
                names = ", ".join(d.name for d in doctors)
                return f"UNKNOWN_DOCTOR: '{doctor_name}' not found. Available doctors: {names}"
            doctor_id = doctor.id

        start = datetime.fromisoformat(date_from) if date_from else None
        end = datetime.fromisoformat(date_to) if date_to else None

        slots = await scheduling_service.check_availability(
            db, clinic_id=clinic_id, service_id=service.id, doctor_id=doctor_id, start=start, end=end
        )
        if not slots:
            return "NO_SLOTS: no availability found in that window. Suggest a wider date range."
        return "\n".join(_fmt_slot(s) for s in slots)

    async def book_appointment(
        patient_name: str,
        patient_phone: str,
        service_name: str,
        slot_id: str,
        doctor_name: str | None = None,
        notes: str | None = None,
    ) -> str:
        service = await scheduling_service.resolve_service(db, clinic_id=clinic_id, name=service_name)
        if service is None:
            return f"UNKNOWN_SERVICE: '{service_name}' not found."

        try:
            slot_uuid = uuid.UUID(slot_id)
        except ValueError:
            return "INVALID_SLOT_ID: slot_id must be the exact value returned by check_availability."

        # Resolve doctor from the slot itself if not given, so the doctor_id matches the slot.
        slots = await scheduling_service.check_availability(
            db, clinic_id=clinic_id, service_id=service.id, limit=200
        )
        slot = next((s for s in slots if s.id == slot_uuid), None)
        if slot is None:
            return "SLOT_NOT_FOUND: that slot is no longer available. Call check_availability again."

        patient = await scheduling_service.get_or_create_patient(
            db, clinic_id=clinic_id, name=patient_name, phone=patient_phone, preferred_language=language
        )

        try:
            appointment = await scheduling_service.create_appointment(
                db,
                clinic_id=clinic_id,
                patient_id=patient.id,
                doctor_id=slot.doctor_id,
                service_id=service.id,
                slot_id=slot.id,
                notes=notes,
            )
        except SlotUnavailableError:
            await db.rollback()
            return "SLOT_TAKEN: that slot was just booked by someone else. Offer to check_availability again."
        except (NotFoundError, SchedulingError) as exc:
            await db.rollback()
            return f"BOOKING_FAILED: {exc}"

        await db.commit()
        return (
            f"BOOKED: appointment_id={appointment.id} for {patient_name} on "
            f"{appointment.start_time.strftime(_DATE_FMT)} ({service.name})."
        )

    async def find_my_appointments(patient_phone: str) -> str:
        appointments = await scheduling_service.find_appointments(db, clinic_id=clinic_id, phone=patient_phone)
        if not appointments:
            return "NO_APPOINTMENTS: no upcoming appointments found for this phone number."
        lines = []
        for a in appointments:
            lines.append(
                f"appointment_id={a.id} | {a.start_time.strftime(_DATE_FMT)} | status={a.status}"
            )
        return "\n".join(lines)

    async def reschedule_appointment(appointment_id: str, new_slot_id: str) -> str:
        try:
            appt_uuid = uuid.UUID(appointment_id)
            slot_uuid = uuid.UUID(new_slot_id)
        except ValueError:
            return "INVALID_ID: appointment_id/new_slot_id must be exact values from prior tool results."

        try:
            appointment = await scheduling_service.reschedule_appointment(
                db, clinic_id=clinic_id, appointment_id=appt_uuid, new_slot_id=slot_uuid
            )
        except NotFoundError:
            await db.rollback()
            return "NOT_FOUND: no such appointment for this clinic."
        except SlotUnavailableError:
            await db.rollback()
            return "SLOT_TAKEN: that slot is no longer available. Call check_availability again."
        except SchedulingError as exc:
            await db.rollback()
            return f"RESCHEDULE_FAILED: {exc}"

        await db.commit()
        return f"RESCHEDULED: appointment_id={appointment.id} moved to {appointment.start_time.strftime(_DATE_FMT)}."

    async def cancel_appointment(appointment_id: str, reason: str | None = None) -> str:
        try:
            appt_uuid = uuid.UUID(appointment_id)
        except ValueError:
            return "INVALID_ID: appointment_id must be the exact value from find_my_appointments."

        try:
            appointment = await scheduling_service.cancel_appointment(
                db, clinic_id=clinic_id, appointment_id=appt_uuid, reason=reason
            )
        except NotFoundError:
            await db.rollback()
            return "NOT_FOUND: no such appointment for this clinic."
        except SchedulingError as exc:
            await db.rollback()
            return f"CANCEL_FAILED: {exc}"

        await db.commit()
        return f"CANCELLED: appointment_id={appointment.id}."

    return [
        StructuredTool.from_function(
            coroutine=search_clinic_kb,
            name="search_clinic_kb",
            description=(
                "Search the clinic's FAQ/knowledge base (hours, services, pricing, location, policies, "
                "insurance, doctor info). Always use this before answering any factual question about "
                "the clinic - never guess."
            ),
            args_schema=SearchKBArgs,
        ),
        StructuredTool.from_function(
            coroutine=check_availability,
            name="check_availability",
            description="Find open appointment slots for a service, optionally with a preferred doctor and date range.",
            args_schema=CheckAvailabilityArgs,
        ),
        StructuredTool.from_function(
            coroutine=book_appointment,
            name="book_appointment",
            description=(
                "Book an appointment. Only call this AFTER reading back the patient's name, phone number, "
                "and chosen slot for confirmation."
            ),
            args_schema=BookAppointmentArgs,
        ),
        StructuredTool.from_function(
            coroutine=find_my_appointments,
            name="find_my_appointments",
            description="Look up a patient's upcoming appointments by phone number. Required before reschedule or cancel.",
            args_schema=FindAppointmentsArgs,
        ),
        StructuredTool.from_function(
            coroutine=reschedule_appointment,
            name="reschedule_appointment",
            description="Move an existing appointment to a new slot. Confirm the new time with the patient first.",
            args_schema=RescheduleAppointmentArgs,
        ),
        StructuredTool.from_function(
            coroutine=cancel_appointment,
            name="cancel_appointment",
            description="Cancel an existing appointment. Confirm with the patient before calling this.",
            args_schema=CancelAppointmentArgs,
        ),
    ]
