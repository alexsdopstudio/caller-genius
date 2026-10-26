from typing import Annotated
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, EmailStr, AwareDatetime

Phone = Annotated[str, Field(pattern=r'^\+[1-9]\d{7,14}$')]


class ProspectCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    owner_name: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    service_type: str = Field(min_length=1, max_length=300)
    landline_phone: Phone
    mobile_phone: Phone | None = None


class ProspectOut(ProspectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    audit_status: str
    qual_status: str
    generated_outreach_text: str | None
    demo_state: str
    demo_conversation_id: str | None
    audit_timestamp: datetime | None
    audit_ring_duration: int | None


class DemoRequest(BaseModel):
    prospect_id: str
    token: str
    mobile_phone: Phone
    consent: bool
    whatsapp_consent: bool = False


class ProspectTool(BaseModel):
    prospect_id: str


class BookingRequest(ProspectTool):
    preferred_slot: AwareDatetime
    owner_name: str | None = Field(default=None, max_length=100)
    company_name: str | None = Field(default=None, max_length=200)
    prospect_email: EmailStr | None = None
