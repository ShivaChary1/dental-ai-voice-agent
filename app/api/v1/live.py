import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.security import decode_access_token
from app.services.realtime import subscribe_call_events

router = APIRouter(tags=["live"])


@router.websocket("/ws/live-calls")
async def live_calls(websocket: WebSocket, token: str = Query(...)) -> None:
    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=4401)
        return

    clinic_id = payload["clinic_id"]
    await websocket.accept()

    pubsub = await subscribe_call_events(clinic_id)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                await websocket.send_text(message["data"])
            else:
                # Keep the connection alive and notice client disconnects promptly.
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                except asyncio.TimeoutError:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
