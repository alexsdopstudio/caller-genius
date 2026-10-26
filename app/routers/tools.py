from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from app.database import get_db
from app.models import Prospect, CallLog, now
from app.schemas import ProspectTool, BookingRequest
from app.security import tool_auth, verify_elevenlabs
from app.services import calendar
from app.services.messaging import send_whatsapp

router = APIRouter(prefix='/api/tools', tags=['ElevenLabs tools'])


async def active_prospect(db, prospect_id):
    p = await db.get(Prospect, prospect_id)
    if not p or p.demo_state not in {'starting', 'started', 'completed'}:
        raise HTTPException(404, 'Active demo not found')
    return p


@router.post('/send-whatsapp-simulation', dependencies=[Depends(tool_auth)])
async def simulation(body: ProspectTool, db=Depends(get_db)):
    p = await active_prospect(db, body.prospect_id)
    if not p.whatsapp_consent:
        return {'status': 'skipped_no_consent', 'message': 'Il titolare non ha richiesto WhatsApp. Prosegui senza invio.'}
    claimed = await db.execute(update(Prospect).where(Prospect.id == p.id, Prospect.simulation_message_state == 'ready')
                               .values(simulation_message_state='sending'))
    if claimed.rowcount != 1:
        return {'status': p.simulation_message_state, 'message': 'Richiesta già elaborata; non annunciare un nuovo invio.'}
    await db.commit()
    try:
        p.simulation_message_state = await send_whatsapp(p, f'[SIMULAZIONE AI] Assistente di {p.company_name}: qui potresti inviare foto o dettagli per il preventivo. Non occorre inviare documenti reali per questa demo.')
    except Exception:
        p.simulation_message_state = 'unknown'
    await db.commit()
    return {'status': p.simulation_message_state, 'message': 'Esito richiesta WhatsApp; accepted non garantisce consegna.'}


@router.post('/check-calendar', dependencies=[Depends(tool_auth)])
async def check_calendar(db=Depends(get_db)):
    return await calendar.availability(db)


@router.post('/book-sales-meeting', dependencies=[Depends(tool_auth)])
async def book_meeting(body: BookingRequest, db=Depends(get_db)):
    p = await active_prospect(db, body.prospect_id)
    return await calendar.book(db, p, body)


@router.post('/post-call-webhook', dependencies=[Depends(verify_elevenlabs)])
async def post_call(request: Request, db=Depends(get_db)):
    try:
        payload = await request.json()
        if payload.get('type') != 'post_call_transcription':
            return {'status': 'ignored'}
        data = payload['data']
        conversation_id = data['conversation_id']
        if not isinstance(conversation_id, str):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(422, 'Invalid post-call event')
    log = await db.scalar(select(CallLog).where(CallLog.provider_id == conversation_id, CallLog.kind == 'demo'))
    if not log:
        # The provider can deliver the webhook before the outbound HTTP response is persisted.
        raise HTTPException(503, 'Conversation not persisted yet; retry webhook')
    if log.status == 'completed':
        return {'status': 'already_processed'}
    log.payload = data
    log.status = 'completed'
    log.finished_at = now()
    duration = data.get('metadata', {}).get('call_duration_secs')
    if isinstance(duration, (int, float)) and duration >= 0:
        log.duration_seconds = int(duration)
    p = await db.get(Prospect, log.prospect_id)
    if p.demo_conversation_id == conversation_id:
        p.demo_state = 'completed'
    if p.qual_status != 'meeting_booked':
        p.qual_status = 'demo_completed'
    await db.commit()
    return {'status': 'ok'}
