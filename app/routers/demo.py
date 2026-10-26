from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from app.database import get_db
from app.models import Prospect, CallLog, now
from app.schemas import DemoRequest
from app.security import check_magic, twilio_form
from app.services.elevenlabs import start_call

router = APIRouter(tags=['Demo'])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))


async def trigger_demo(db, p, phone, whatsapp_consent):
    # Conditional UPDATE is the cross-process claim: simultaneous clicks cannot call twice.
    try:
        result = await db.execute(update(Prospect).where(Prospect.id == p.id, Prospect.demo_state == 'ready')
                                  .values(demo_state='starting', mobile_phone=phone,
                                          whatsapp_consent=whatsapp_consent, demo_triggered_at=now()))
        if result.rowcount != 1:
            raise HTTPException(409, 'Demo già richiesta. Chiedi un nuovo invito per ripeterla.')
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, 'Numero già associato a un altro prospect')
    await db.refresh(p)
    try:
        result = await start_call(p)
    except HTTPException:
        p.demo_state = 'unknown'
        await db.commit()
        raise
    p.demo_conversation_id = result['conversation_id']
    p.demo_state = 'started'
    db.add(CallLog(prospect_id=p.id, kind='demo', provider_id=result['conversation_id'], status='started'))
    await db.commit()
    return {'status': 'started', 'conversation_id': result['conversation_id']}


@router.get('/prova/{prospect_id}', response_class=HTMLResponse)
async def landing(request: Request, prospect_id: str, token: str, db=Depends(get_db)):
    p = await db.get(Prospect, prospect_id)
    if not p:
        raise HTTPException(404, 'Invito non trovato')
    check_magic(p, token)
    return templates.TemplateResponse(request=request, name='demo.html', context={'p': p, 'token': token})


@router.post('/api/demo/trigger')
async def trigger(body: DemoRequest, db=Depends(get_db)):
    p = await db.get(Prospect, body.prospect_id)
    if not p:
        raise HTTPException(404, 'Invito non trovato')
    check_magic(p, body.token)
    if not body.consent:
        raise HTTPException(422, 'Conferma la richiesta di chiamata')
    return await trigger_demo(db, p, body.mobile_phone, body.whatsapp_consent)


@router.post('/api/demo/whatsapp')
async def whatsapp(request: Request, db=Depends(get_db)):
    form = await twilio_form(request)
    if str(form.get('Body', '')).strip().upper() != 'PROVA':
        return Response('<Response/>', media_type='application/xml')
    phone = str(form.get('From', '')).removeprefix('whatsapp:')
    p = await db.scalar(select(Prospect).where(Prospect.mobile_phone == phone))
    if p and p.demo_state == 'ready':
        await trigger_demo(db, p, phone, True)
    return Response('<Response/>', media_type='application/xml')
