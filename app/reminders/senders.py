"""Reminder delivery channels.

SMS/WhatsApp are sent via Twilio. Voice reminders require an outbound
telephony path (LiveKit SIP trunk) which was deferred for v1 (web-widget-only
voice agent) - `send_voice` raises `ChannelNotConfigured` so the scheduler
marks the reminder as failed with a clear, actionable error instead of
silently dropping it.
"""

from twilio.rest import Client as TwilioClient

from app.config import settings


class ChannelNotConfigured(Exception):
    pass


class SendError(Exception):
    pass


_twilio: TwilioClient | None = None


def _get_twilio() -> TwilioClient:
    global _twilio
    if _twilio is None:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise ChannelNotConfigured("Twilio credentials are not configured")
        _twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    return _twilio


def send_sms(*, to: str, body: str) -> str:
    if not settings.twilio_sms_from:
        raise ChannelNotConfigured("TWILIO_SMS_FROM is not configured")
    client = _get_twilio()
    try:
        message = client.messages.create(to=to, from_=settings.twilio_sms_from, body=body)
    except Exception as exc:  # noqa: BLE001 - surface as SendError for the scheduler to record
        raise SendError(str(exc)) from exc
    return message.sid


def send_whatsapp(*, to: str, body: str) -> str:
    if not settings.twilio_whatsapp_from:
        raise ChannelNotConfigured("TWILIO_WHATSAPP_FROM is not configured")
    client = _get_twilio()
    try:
        message = client.messages.create(
            to=f"whatsapp:{to}", from_=settings.twilio_whatsapp_from, body=body
        )
    except Exception as exc:  # noqa: BLE001
        raise SendError(str(exc)) from exc
    return message.sid


def send_voice(*, to: str, body: str) -> str:
    raise ChannelNotConfigured(
        "Outbound voice reminders require a LiveKit SIP trunk / telephony integration, "
        "which is not configured in this deployment. Use 'sms' or 'whatsapp' channels."
    )


_SENDERS = {"sms": send_sms, "whatsapp": send_whatsapp, "voice": send_voice}


def send(channel: str, *, to: str, body: str) -> str:
    sender = _SENDERS.get(channel)
    if sender is None:
        raise ChannelNotConfigured(f"Unknown reminder channel: {channel}")
    return sender(to=to, body=body)
