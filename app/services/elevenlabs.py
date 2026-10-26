import uuid
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException
from app.config import get_settings
from app.models import now


async def start_call(prospect):
    s = get_settings()
    stamp = prospect.audit_timestamp or now()
    if stamp.tzinfo is None:
        from datetime import timezone
        stamp = stamp.replace(tzinfo=timezone.utc)
    payload = {
        'agent_id': s.elevenlabs_agent_id,
        'agent_phone_number_id': s.elevenlabs_phone_number_id,
        'to_number': prospect.mobile_phone,
        'conversation_initiation_client_data': {'dynamic_variables': {
            'prospect_id': prospect.id, 'company_name': prospect.company_name,
            'owner_name': prospect.owner_name, 'city': prospect.city,
            'service_type': prospect.service_type,
            'audit_time': stamp.astimezone(ZoneInfo(s.timezone)).strftime('%H:%M') if prospect.audit_timestamp else 'non disponibile',
        }},
    }
    if s.simulated:
        return {'success': True, 'conversation_id': 'mock-' + str(uuid.uuid4()), 'callSid': None}
    # Never retry a potentially accepted outbound call automatically.
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            response = await client.post('https://api.elevenlabs.io/v1/convai/twilio/outbound-call',
                                         headers={'xi-api-key': s.elevenlabs_api_key}, json=payload)
            response.raise_for_status()
            result = response.json()
            if not result.get('success') or not result.get('conversation_id'):
                raise ValueError('Missing successful conversation')
            return result
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Esito provider da verificare. Non ripetere la chiamata prima della verifica.')
