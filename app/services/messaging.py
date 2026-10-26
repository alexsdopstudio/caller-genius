import asyncio
from twilio.rest import Client
from app.config import get_settings


async def send_whatsapp(prospect, text):
    s = get_settings()
    if not prospect.mobile_phone or not prospect.whatsapp_consent:
        return 'skipped_no_consent'
    if s.simulated:
        return 'mock_sent'
    client = Client(s.twilio_account_sid, s.twilio_auth_token)
    await asyncio.to_thread(client.messages.create, from_=s.twilio_whatsapp_from,
                            to='whatsapp:' + prospect.mobile_phone, body=text)
    return 'accepted'
