"""Offline eval harness for the conversation agent.

Runs each case in evals/cases.yaml against the seeded "smile-care-dental"
clinic (run `python -m scripts.seed_db` first), grades tool usage and final
outcome programmatically, and prints a pass/fail summary.

Usage:
    python -m evals.run_eval
"""

import asyncio
import sys
import uuid

import yaml
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

from app.agent.checkpointer import close_checkpointer
from app.agent.graph import get_final_state, stream_turn
from app.db.models import Clinic
from app.db.session import AsyncSessionLocal

CASES_PATH = "evals/cases.yaml"


async def _load_clinic(db) -> Clinic:
    clinic = await db.scalar(select(Clinic).where(Clinic.slug == "smile-care-dental"))
    if clinic is None:
        raise RuntimeError("Seed clinic not found - run `python -m scripts.seed_db` first")
    return clinic


def _tool_calls_used(messages: list) -> set[str]:
    names: set[str] = set()
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                names.add(call["name"])
    return names


async def run_case(db, clinic: Clinic, case: dict) -> tuple[bool, str]:
    thread_id = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    language = case.get("language", "en-IN")

    for turn in case["turns"]:
        async for _ in stream_turn(db, clinic=clinic, language=language, config=config, user_text=turn):
            pass

    state = await get_final_state(db, clinic=clinic, language=language, config=config)
    used_tools = _tool_calls_used(state["messages"])

    failures = []

    expected_tools = set(case.get("expected_tools", []))
    missing = expected_tools - used_tools
    if missing:
        failures.append(f"missing expected tool calls: {sorted(missing)}")

    forbidden_tools = set(case.get("forbidden_tools", []))
    present = forbidden_tools & used_tools
    if present:
        failures.append(f"called forbidden tools: {sorted(present)}")

    expected_outcome = case.get("expected_outcome")
    if expected_outcome and state["outcome"] != expected_outcome:
        failures.append(f"expected outcome '{expected_outcome}', got '{state['outcome']}'")

    if failures:
        return False, "; ".join(failures)
    return True, "ok"


async def main() -> int:
    with open(CASES_PATH, encoding="utf-8") as f:
        cases = yaml.safe_load(f)

    passed = 0
    async with AsyncSessionLocal() as db:
        clinic = await _load_clinic(db)

        for case in cases:
            ok, detail = await run_case(db, clinic, case)
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {case['id']}: {detail}")
            if ok:
                passed += 1

    total = len(cases)
    print(f"\n{passed}/{total} cases passed")
    await close_checkpointer()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
