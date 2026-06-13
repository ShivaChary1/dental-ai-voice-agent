from fastapi import APIRouter

from app.api.v1 import appointments, auth, calls, kb, live, metrics, patients, reminders

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(calls.router)
api_router.include_router(appointments.router)
api_router.include_router(patients.router)
api_router.include_router(kb.router)
api_router.include_router(metrics.router)
api_router.include_router(reminders.router)

ws_router = APIRouter()
ws_router.include_router(live.router)
