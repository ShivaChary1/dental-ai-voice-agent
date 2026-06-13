"""Localized reminder message templates.

Templates are intentionally plain string formatting (no LLM call) - reminder
volume can be high and the content is fully deterministic, so spending an LLM
call per reminder would be pure cost with no quality benefit.
"""

from datetime import datetime

_TEMPLATES: dict[str, str] = {
    "en-IN": (
        "Hi {patient_name}, this is a reminder from {clinic_name} for your "
        "{service_name} appointment on {date} at {time} with {doctor_name}. "
        "Reply CANCEL to cancel or call us to reschedule."
    ),
    "hi-IN": (
        "नमस्ते {patient_name}, यह {clinic_name} से आपकी {date} को {time} बजे "
        "{doctor_name} के साथ {service_name} अपॉइंटमेंट की याद दिलाने वाला संदेश है। "
        "रद्द करने के लिए CANCEL भेजें या पुनर्निर्धारण के लिए हमें कॉल करें।"
    ),
    "te-IN": (
        "నమస్తే {patient_name}, ఇది {clinic_name} నుండి {date} న {time} గంటలకు "
        "{doctor_name} తో మీ {service_name} అపాయింట్‌మెంట్ గుర్తు చేయడం. "
        "రద్దు చేయడానికి CANCEL అని రిప్లై చేయండి లేదా రీషెడ్యూల్ కోసం మాకు కాల్ చేయండి."
    ),
}

_DEFAULT_LANGUAGE = "en-IN"


def render_reminder_message(
    *,
    language: str,
    patient_name: str,
    clinic_name: str,
    service_name: str,
    doctor_name: str,
    start_time: datetime,
) -> str:
    template = _TEMPLATES.get(language, _TEMPLATES[_DEFAULT_LANGUAGE])
    return template.format(
        patient_name=patient_name,
        clinic_name=clinic_name,
        service_name=service_name,
        doctor_name=doctor_name,
        date=start_time.strftime("%d %b %Y"),
        time=start_time.strftime("%I:%M %p"),
    )
