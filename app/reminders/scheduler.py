"""Background reminder worker.

Runs as its own process (`python -m app.reminders.scheduler`). Every tick it:

1. Marks `scheduled` appointments whose start time has passed as `completed`
   and clears any pending reminder for them.
2. Finds `scheduled` appointments due for their next reminder
   (`next_reminder_at <= now`), sends it on each configured channel, records
   a `Reminder` row per attempt, and advances `reminder_stage` /
   `next_reminder_at` according to the clinic's cadence - or clears it once
   the cadence is exhausted.

Each appointment is processed in its own transaction so one failure can't
roll back progress on the rest of the batch.
"""

import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.db.models import Appointment, Clinic, Doctor, Patient, Reminder, Service
from app.db.session import AsyncSessionLocal
from app.logging_config import configure_logging, get_logger
from app.reminders.messages import render_reminder_message
from app.reminders.senders import ChannelNotConfigured, SendError, send

configure_logging()
logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 60

DEFAULT_REMINDER_CONFIG = {
    "channels": ["sms"],
    "cadence_hours": [48, 24, 2],
    "max_attempts": 3,
}


async def _complete_past_appointments() -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        await db.execute(
            update(Appointment)
            .where(Appointment.status == "scheduled", Appointment.start_time < now)
            .values(status="completed", next_reminder_at=None)
        )
        await db.commit()


async def _due_appointment_ids(limit: int = 50) -> list:
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        stmt = (
            select(Appointment.id)
            .where(
                Appointment.status == "scheduled",
                Appointment.next_reminder_at.is_not(None),
                Appointment.next_reminder_at <= now,
            )
            .limit(limit)
        )
        return list((await db.scalars(stmt)).all())


async def _process_appointment(appointment_id) -> None:
    async with AsyncSessionLocal() as db:
        appointment = await db.get(Appointment, appointment_id)
        if appointment is None or appointment.status != "scheduled":
            return

        clinic = await db.get(Clinic, appointment.clinic_id)
        patient = await db.get(Patient, appointment.patient_id)
        doctor = await db.get(Doctor, appointment.doctor_id)
        service = await db.get(Service, appointment.service_id)
        if not all([clinic, patient, doctor, service]):
            logger.warning("reminder_skip_missing_refs", appointment_id=str(appointment_id))
            appointment.next_reminder_at = None
            await db.commit()
            return

        config = {**DEFAULT_REMINDER_CONFIG, **(clinic.reminder_config or {})}
        cadence_hours: list[int] = config.get("cadence_hours", DEFAULT_REMINDER_CONFIG["cadence_hours"])
        channels: list[str] = config.get("channels", DEFAULT_REMINDER_CONFIG["channels"])
        max_attempts: int = config.get("max_attempts", DEFAULT_REMINDER_CONFIG["max_attempts"])

        stage = appointment.reminder_stage

        message = render_reminder_message(
            language=patient.preferred_language,
            patient_name=patient.name,
            clinic_name=clinic.name,
            service_name=service.name,
            doctor_name=doctor.name,
            start_time=appointment.start_time,
        )

        for channel in channels:
            reminder = Reminder(
                clinic_id=appointment.clinic_id,
                appointment_id=appointment.id,
                channel=channel,
                scheduled_at=appointment.next_reminder_at,
                message=message,
                attempt_count=1,
            )
            try:
                await asyncio.to_thread(send, channel, to=patient.phone, body=message)
                reminder.status = "sent"
                reminder.sent_at = datetime.utcnow()
            except (ChannelNotConfigured, SendError) as exc:
                reminder.status = "failed"
                reminder.error = str(exc)
                logger.error(
                    "reminder_send_failed",
                    appointment_id=str(appointment.id),
                    channel=channel,
                    error=str(exc),
                )
            db.add(reminder)

        next_stage = stage + 1
        if next_stage < len(cadence_hours) and next_stage < max_attempts:
            appointment.reminder_stage = next_stage
            appointment.next_reminder_at = appointment.start_time - timedelta(hours=cadence_hours[next_stage])
            # If that computed time is already in the past (e.g. appointment booked
            # last-minute), fire it on the next tick instead of waiting.
            if appointment.next_reminder_at < datetime.utcnow():
                appointment.next_reminder_at = datetime.utcnow() + timedelta(seconds=POLL_INTERVAL_SECONDS)
        else:
            appointment.reminder_stage = next_stage
            appointment.next_reminder_at = None

        await db.commit()


async def run_once() -> None:
    await _complete_past_appointments()
    for appointment_id in await _due_appointment_ids():
        await _process_appointment(appointment_id)


def start() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_once, "interval", seconds=POLL_INTERVAL_SECONDS, id="reminder_tick", max_instances=1)
    scheduler.start()
    logger.info("reminder_scheduler_started", interval_seconds=POLL_INTERVAL_SECONDS)
    return scheduler


async def main() -> None:
    start()
    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
