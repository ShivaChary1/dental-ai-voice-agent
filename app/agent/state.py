import uuid
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

Outcome = Literal["faq", "booked", "rescheduled", "cancelled", "escalated", "no_outcome"]


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

    # Per-call context (set once at session start, read-only afterwards)
    clinic_id: str
    call_session_id: str
    caller_phone: str | None
    language: str

    # Mutable conversation bookkeeping
    patient_id: str | None
    turn_count: int
    outcome: Outcome


def initial_state(
    *,
    clinic_id: uuid.UUID,
    call_session_id: uuid.UUID,
    caller_phone: str | None,
    language: str,
) -> AgentState:
    return AgentState(
        messages=[],
        clinic_id=str(clinic_id),
        call_session_id=str(call_session_id),
        caller_phone=caller_phone,
        language=language,
        patient_id=None,
        turn_count=0,
        outcome="no_outcome",
    )
