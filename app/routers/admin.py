from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from urllib.parse import quote
from app.config import get_settings
from app.database import get_db
from app.models import Prospect, CallLog, Meeting, uid
from app.schemas import ProspectCreate, ProspectOut
from app.security import admin, magic_token
from app.routers.demo import templates

router = APIRouter(dependencies=[Depends(admin)], tags=['Admin'])


@router.get('/admin/prospects', response_class=HTMLResponse)
async def dashboard(request: Request, db=Depends(get_db)):
    prospects = (await db.scalars(select(Prospect).order_by(Prospect.company_name).limit(500))).all()
    return templates.TemplateResponse(request=request, name='admin.html', context={
        'prospects': prospects, 'mock': get_settings().simulated,
        'token_for': magic_token, 'quote': quote,
    })


@router.post('/api/prospects', response_model=ProspectOut, status_code=201)
async def create(body: ProspectCreate, db=Depends(get_db)):
    p = Prospect(**body.model_dump())
    db.add(p)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, 'Numero fisso o cellulare già presente')
    return p


@router.get('/api/prospects', response_model=list[ProspectOut])
async def list_prospects(offset: int = 0, db=Depends(get_db)):
    if offset < 0:
        raise HTTPException(422, 'Offset non valido')
    return (await db.scalars(select(Prospect).offset(offset).limit(100))).all()


@router.get('/api/prospects/{prospect_id}/invite')
async def invite(prospect_id: str, db=Depends(get_db)):
    p = await db.get(Prospect, prospect_id)
    if not p:
        raise HTTPException(404, 'Prospect non trovato')
    token = magic_token(p)
    return {'token': token, 'url': f'{get_settings().public_base_url}/prova/{p.id}?token={token}'}


@router.post('/api/prospects/{prospect_id}/reset-demo')
async def reset(prospect_id: str, db=Depends(get_db)):
    p = await db.get(Prospect, prospect_id)
    if not p:
        raise HTTPException(404, 'Prospect non trovato')
    if p.demo_state not in {'completed', 'ready'}:
        raise HTTPException(409, 'Demo in corso o esito incerto: riconciliare il provider prima del reset')
    p.demo_nonce = uid()
    p.demo_state = 'ready'
    p.demo_conversation_id = None
    p.simulation_message_state = 'ready'
    p.whatsapp_consent = False
    p.generated_outreach_text = None
    await db.commit()
    return {'status': 'ready'}


@router.get('/api/prospects/{prospect_id}/history')
async def history(prospect_id: str, db=Depends(get_db)):
    logs = (await db.scalars(select(CallLog).where(CallLog.prospect_id == prospect_id))).all()
    meetings = (await db.scalars(select(Meeting).where(Meeting.prospect_id == prospect_id))).all()
    return {'calls': logs, 'meetings': meetings}
