from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AuthedUser, DbSession
from app.db.models import CallSession, CallTurn, Reminder
from app.schemas.reminders import MetricsOverview

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/overview", response_model=MetricsOverview)
async def overview(db: DbSession, user: AuthedUser, days: int = Query(default=7, le=90)) -> MetricsOverview:
    since = datetime.utcnow() - timedelta(days=days)

    calls_stmt = select(CallSession).where(
        CallSession.clinic_id == user.clinic_id, CallSession.started_at >= since
    )
    calls = list((await db.scalars(calls_stmt)).all())

    total_calls = len(calls)
    outcome_counts = {"booked": 0, "rescheduled": 0, "cancelled": 0, "faq": 0, "escalated": 0, "no_outcome": 0}
    language_counts: dict[str, int] = {}
    for call in calls:
        outcome_counts[call.outcome or "no_outcome"] = outcome_counts.get(call.outcome or "no_outcome", 0) + 1
        language_counts[call.language] = language_counts.get(call.language, 0) + 1

    bookings = outcome_counts["booked"]
    reschedules = outcome_counts["rescheduled"]
    cancellations = outcome_counts["cancelled"]
    faq_only = outcome_counts["faq"]
    escalated = outcome_counts["escalated"]

    booking_conversion_rate = bookings / total_calls if total_calls else 0.0
    escalation_rate = escalated / total_calls if total_calls else 0.0

    latency_stmt = select(CallTurn.total_ms).join(CallSession, CallSession.id == CallTurn.call_session_id).where(
        CallSession.clinic_id == user.clinic_id,
        CallSession.started_at >= since,
        CallTurn.role == "assistant",
        CallTurn.total_ms.is_not(None),
    )
    latencies = sorted(v for v in (await db.scalars(latency_stmt)).all() if v is not None)

    def _percentile(values: list[int], pct: float) -> float | None:
        if not values:
            return None
        idx = min(len(values) - 1, int(len(values) * pct))
        return float(values[idx])

    pending_reminders_stmt = select(func.count(Reminder.id)).where(
        Reminder.clinic_id == user.clinic_id, Reminder.status == "pending"
    )
    pending_reminders = (await db.scalar(pending_reminders_stmt)) or 0

    return MetricsOverview(
        period_days=days,
        total_calls=total_calls,
        bookings=bookings,
        reschedules=reschedules,
        cancellations=cancellations,
        faq_only=faq_only,
        escalated=escalated,
        booking_conversion_rate=round(booking_conversion_rate, 4),
        escalation_rate=round(escalation_rate, 4),
        language_breakdown=language_counts,
        latency_p50_ms=_percentile(latencies, 0.5),
        latency_p95_ms=_percentile(latencies, 0.95),
        pending_reminders=pending_reminders,
    )
