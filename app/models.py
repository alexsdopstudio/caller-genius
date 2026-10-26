import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class Prospect(Base):
    __tablename__ = 'prospects'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    company_name: Mapped[str] = mapped_column(String(200))
    owner_name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100))
    service_type: Mapped[str] = mapped_column(String(300))
    landline_phone: Mapped[str] = mapped_column(String(20), unique=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    audit_status: Mapped[str] = mapped_column(String(30), default='pending')
    audit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_ring_duration: Mapped[int | None]
    active_audit_id: Mapped[str | None] = mapped_column(String(36))
    demo_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demo_conversation_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    qual_status: Mapped[str] = mapped_column(String(30), default='new')
    generated_outreach_text: Mapped[str | None] = mapped_column(Text)
    demo_nonce: Mapped[str] = mapped_column(String(36), default=uid)
    demo_state: Mapped[str] = mapped_column(String(30), default='ready')
    whatsapp_consent: Mapped[bool] = mapped_column(default=False)
    simulation_message_state: Mapped[str] = mapped_column(String(30), default='ready')


class CallLog(Base):
    __tablename__ = 'call_logs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    prospect_id: Mapped[str] = mapped_column(ForeignKey('prospects.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    provider_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(40), default='starting')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ringing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None]
    payload: Mapped[dict | None] = mapped_column(JSON)


class Meeting(Base):
    __tablename__ = 'meetings'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    prospect_id: Mapped[str] = mapped_column(ForeignKey('prospects.id'), unique=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), unique=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    prospect_email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(30), default='pending')
    notification_status: Mapped[str] = mapped_column(String(30), default='not_sent')
