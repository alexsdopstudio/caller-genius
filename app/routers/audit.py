from fastapi import APIRouter, Depends, HTTPException, Request
from app.database import get_db
from app.models import Prospect, CallLog
from app.security import admin, twilio_form
from app.services.twilio_audit import run_audit, apply_status

router = APIRouter(prefix='/api/audit', tags=['Audit'])


@router.post('/{prospect_id}/start', dependencies=[Depends(admin)])
async def start(prospect_id: str, db=Depends(get_db)):
    p = await db.get(Prospect, prospect_id)
    if not p:
        raise HTTPException(404, 'Prospect non trovato')
    return await run_audit(db, p)


@router.post('/twilio-status-callback')
async def status(request: Request, attempt: str, db=Depends(get_db)):
    form = await twilio_form(request)
    log = await db.get(CallLog, attempt)
    if not log or log.kind != 'audit':
        raise HTTPException(404, 'Attempt not found')
    sid = form.get('CallSid')
    if not sid or (log.provider_id and log.provider_id != sid):
        raise HTTPException(400, 'Call SID mismatch')
    log.provider_id = sid
    await apply_status(db, log, form.get('CallStatus'), form)
    return {'status': 'ok'}
