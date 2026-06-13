import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AuthedUser, DbSession
from app.db.models import Reminder
from app.schemas.reminders import ReminderOut

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("", response_model=list[ReminderOut])
async def list_reminders(
    db: DbSession,
    user: AuthedUser,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> list[Reminder]:
    stmt = select(Reminder).where(Reminder.clinic_id == user.clinic_id)
    if status_filter:
        stmt = stmt.where(Reminder.status == status_filter)
    stmt = stmt.order_by(Reminder.scheduled_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


@router.post("/{reminder_id}/retry", response_model=ReminderOut)
async def retry_reminder(reminder_id: uuid.UUID, db: DbSession, user: AuthedUser) -> Reminder:
    reminder = await db.get(Reminder, reminder_id)
    if reminder is None or reminder.clinic_id != user.clinic_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reminder not found")

    if reminder.status not in ("failed", "cancelled"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Reminder is {reminder.status}, cannot retry")

    reminder.status = "pending"
    reminder.scheduled_at = datetime.utcnow()
    reminder.error = None
    await db.commit()
    await db.refresh(reminder)
    return reminder
