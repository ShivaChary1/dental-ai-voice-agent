"""LangGraph conversation agent: a single tool-calling loop.

Deliberate design choice: a separate "intent router" LLM call (as sketched in
the original design doc) would add a full extra model round-trip to every
turn, which directly fights the <500ms-first-audio latency budget. Anthropic's
tool-calling already routes between FAQ/RAG, booking, reschedule, and cancel
in one call, so routing is folded into this single agent node and its system
prompt/tool descriptions.
"""

import uuid
from collections.abc import AsyncIterator

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.checkpointer import get_checkpointer
from app.agent.prompts import build_system_prompt
from app.agent.state import AgentState
from app.agent.tools import build_tools
from app.config import settings
from app.db.models import Clinic

MAX_TURNS = 20

_OUTCOME_MARKERS: dict[str, str] = {
    "BOOKED:": "booked",
    "RESCHEDULED:": "rescheduled",
    "CANCELLED:": "cancelled",
    "ESCALATED:": "escalated",
}


def _detect_outcome(messages: list, current: str) -> str:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            content = message.content if isinstance(message.content, str) else str(message.content)
            for marker, outcome in _OUTCOME_MARKERS.items():
                if content.startswith(marker):
                    return outcome
    if current == "no_outcome":
        return "faq"
    return current


async def build_graph(db: AsyncSession, *, clinic: Clinic, language: str):
    tools = build_tools(db, clinic_id=clinic.id, language=language)
    system_prompt = build_system_prompt(clinic, language)

    llm = ChatAnthropic(
        model=settings.llm_model_fast,
        api_key=settings.anthropic_api_key,
        temperature=0.3,
        max_tokens=300,
        timeout=10,
    ).bind_tools(tools)

    async def agent_node(state: AgentState) -> dict:
        turn_count = state["turn_count"] + 1
        if turn_count > MAX_TURNS:
            return {"turn_count": turn_count}

        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt), *messages]
        else:
            messages = [SystemMessage(content=system_prompt), *messages[1:]]

        response = await llm.ainvoke(messages)
        return {"messages": [response], "turn_count": turn_count}

    def route_after_agent(state: AgentState) -> str:
        if state["turn_count"] > MAX_TURNS:
            return "outcome"
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return "outcome"

    async def outcome_node(state: AgentState) -> dict:
        if state["turn_count"] > MAX_TURNS:
            return {
                "messages": [
                    AIMessage(
                        content="I'm having trouble helping with this over the phone - "
                        "I'll have a member of our team call you back shortly."
                    )
                ],
                "outcome": "escalated",
            }
        return {"outcome": _detect_outcome(state["messages"], state["outcome"])}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("outcome", outcome_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "outcome": "outcome"})
    graph.add_edge("tools", "agent")
    graph.add_edge("outcome", END)

    checkpointer = await get_checkpointer()
    return graph.compile(checkpointer=checkpointer)


async def stream_turn(
    db: AsyncSession,
    *,
    clinic: Clinic,
    language: str,
    config: dict,
    user_text: str,
) -> AsyncIterator[str]:
    """Run one conversation turn, yielding response text chunks as they're
    generated (for low-latency streaming TTS).

    `config` must contain {"configurable": {"thread_id": <call_session_id>}}
    so the Postgres checkpointer can resume this call's state.
    """
    graph = await build_graph(db, clinic=clinic, language=language)

    input_state = {
        "messages": [HumanMessage(content=user_text)],
        "clinic_id": str(clinic.id),
        "language": language,
    }

    async for event in graph.astream_events(input_state, config=config, version="v2"):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str) and chunk.content:
                yield chunk.content


async def get_final_state(db: AsyncSession, *, clinic: Clinic, language: str, config: dict) -> AgentState:
    graph = await build_graph(db, clinic=clinic, language=language)
    snapshot = await graph.aget_state(config)
    return snapshot.values
