"""Seed a demo clinic: doctors, services, two weeks of availability slots,
an FAQ knowledge base, and a dashboard login.

Usage:
    python -m scripts.seed_db
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.db.models import Clinic, Doctor, Service, User
from app.db.session import AsyncSessionLocal
from app.security import hash_password
from app.services import kb_service
from app.services.scheduling_service import AvailabilitySlot

CLINIC_SLUG = "smile-care-dental"

FAQ_DOCS = [
    (
        "Clinic hours and location",
        "en-IN",
        "SmileCare Dental is open Monday to Saturday from 9:00 AM to 7:00 PM, "
        "and closed on Sundays and public holidays. We are located at "
        "12-3-45 MG Road, Bengaluru, Karnataka 560001. Free parking is "
        "available in the basement of the building.",
    ),
    (
        "Services and pricing",
        "en-IN",
        "We offer dental cleaning (starting at INR 1,200), cavity fillings "
        "(starting at INR 1,800), root canal treatment (starting at INR "
        "8,000), tooth extraction (starting at INR 1,500), braces "
        "consultation (free), and teeth whitening (starting at INR 6,000). "
        "Exact pricing depends on the complexity of the case and is "
        "confirmed after an in-person examination.",
    ),
    (
        "Insurance and payment",
        "en-IN",
        "We accept cash, all major debit and credit cards, UPI, and most "
        "major health insurance plans including Star Health, HDFC Ergo, and "
        "ICICI Lombard. Please bring your insurance card and a photo ID to "
        "your appointment. We also offer EMI options for treatments above "
        "INR 10,000.",
    ),
    (
        "Appointment policies",
        "en-IN",
        "Appointments can be booked, rescheduled, or cancelled by phone. We "
        "request at least 4 hours notice for cancellations. Please arrive 10 "
        "minutes early for your first visit to complete registration. "
        "Children under 12 must be accompanied by a parent or guardian.",
    ),
]

SERVICES = [
    ("General Checkup & Cleaning", "Routine dental exam and professional cleaning", 30, 1200),
    ("Cavity Filling", "Tooth-coloured composite filling for cavities", 45, 1800),
    ("Root Canal Treatment", "Root canal therapy for infected tooth pulp", 60, 8000),
    ("Tooth Extraction", "Simple tooth extraction", 30, 1500),
    ("Teeth Whitening", "In-office professional teeth whitening", 60, 6000),
]

DOCTORS = [
    ("Dr. Anjali Rao", "General Dentistry"),
    ("Dr. Karthik Iyer", "Endodontics"),
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        clinic = Clinic(
            name="SmileCare Dental",
            slug=CLINIC_SLUG,
            timezone="Asia/Kolkata",
            default_language="en-IN",
            supported_languages=["en-IN", "hi-IN", "te-IN"],
            phone_number="+91 80 1234 5678",
            address="12-3-45 MG Road, Bengaluru, Karnataka 560001",
            reminder_config={"channels": ["sms"], "cadence_hours": [48, 24, 2], "max_attempts": 3},
        )
        db.add(clinic)
        await db.flush()

        services = []
        for name, description, duration, price in SERVICES:
            service = Service(
                clinic_id=clinic.id, name=name, description=description, duration_minutes=duration, price=price
            )
            db.add(service)
            services.append(service)

        doctors = []
        for name, specialization in DOCTORS:
            doctor = Doctor(clinic_id=clinic.id, name=name, specialization=specialization)
            db.add(doctor)
            doctors.append(doctor)

        await db.flush()

        # Two weeks of 30-minute slots, 9am-5pm Mon-Sat, for each doctor.
        start_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        for doctor in doctors:
            for day_offset in range(14):
                day = start_date + timedelta(days=day_offset)
                if day.weekday() == 6:  # Sunday
                    continue
                for hour in range(9, 17):
                    for minute in (0, 30):
                        slot_start = day.replace(hour=hour, minute=minute)
                        db.add(
                            AvailabilitySlot(
                                clinic_id=clinic.id,
                                doctor_id=doctor.id,
                                start_time=slot_start,
                                end_time=slot_start + timedelta(minutes=30),
                                status="available",
                            )
                        )

        db.add(
            User(
                clinic_id=clinic.id,
                email="admin@smilecare.example",
                hashed_password=hash_password("changeme123"),
                role="owner",
            )
        )

        await db.commit()

        for title, language, content in FAQ_DOCS:
            await kb_service.index_document(db, clinic_id=clinic.id, title=title, content=content, language=language)

        print(f"Seeded clinic '{clinic.name}' (id={clinic.id}, slug={clinic.slug})")
        print("Dashboard login: admin@smilecare.example / changeme123")


if __name__ == "__main__":
    asyncio.run(seed())
