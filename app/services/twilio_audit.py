import asyncio
from datetime import timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, update
from twilio.rest import Client
from app.config import get_settings
from app.models import Prospect, CallLog, now, uid
from app.security import magic_token

TERMINAL = {'no-answer': 'no_answer', 'busy': 'busy', 'completed': 'answered', 'failed': 'failed', 'canceled': 'failed'}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def outreach(prospect):
    s = get_settings()
    stamp = utc(prospect.audit_timestamp).astimezone(ZoneInfo(s.timezone)).strftime('%d/%m alle %H:%M')
    outcome = 'il numero risultava occupato' if prospect.audit_status == 'busy' else 'la chiamata non ha ricevuto risposta'
    link = f'{s.public_base_url}/prova/{prospect.id}?token={magic_token(prospect)}'
    return (f'Ciao {prospect.owner_name}, il {stamp} abbiamo provato a chiamare {prospect.company_name}: {outcome}. '
            f'Ti interessa provare una simulazione del nostro assistente AI per {prospect.service_type}? '
            f'Apri {link} oppure rispondi PROVA per richiedere la chiamata demo sul tuo numero.')


async def apply_status(db, log, status, form):
    if status not in TERMINAL and status != 'ringing':
        return
    stamp = now()
    try:
        if form.get('Timestamp'):
            stamp = parsedate_to_datetime(form['Timestamp'])
    except (ValueError, TypeError):
        pass
    if status == 'ringing':
        await db.execute(update(CallLog).where(
            CallLog.id == log.id, ~CallLog.status.in_(list(TERMINAL)), CallLog.ringing_at.is_(None)
        ).values(ringing_at=stamp, status=status))
        await db.commit()
        return
    # Only the first terminal callback claims this attempt, even under concurrency.
    claimed = await db.execute(update(CallLog).where(
        CallLog.id == log.id, ~CallLog.status.in_(list(TERMINAL))
    ).values(status=status, finished_at=stamp))
    if claimed.rowcount != 1:
        await db.rollback()
        return
    await db.refresh(log)
    if form.get('CallDuration', '').isdigit():
        log.duration_seconds = int(form['CallDuration'])
    p = await db.get(Prospect, log.prospect_id)
    if p.active_audit_id == log.id:
        p.audit_status = TERMINAL[status]
        p.audit_timestamp = log.started_at
        if log.ringing_at and status in {'no-answer', 'busy'}:
            p.audit_ring_duration = max(0, int((utc(stamp) - utc(log.ringing_at)).total_seconds()))
        if p.qual_status == 'new':
            p.qual_status = 'audited'
        p.generated_outreach_text = outreach(p) if p.audit_status in {'no_answer', 'busy'} else None
    await db.commit()


async def run_audit(db, prospect):
    s = get_settings()
    log = CallLog(id=uid(), prospect_id=prospect.id, kind='audit', started_at=now())
    result = await db.execute(update(Prospect).where(Prospect.id == prospect.id, Prospect.audit_status == 'pending')
                              .values(audit_status='starting', active_audit_id=log.id))
    if result.rowcount != 1:
        raise HTTPException(409, 'Audit già avviato; verificare lo stato prima di ripeterlo')
    db.add(log)
    await db.commit()
    if s.simulated:
        log.provider_id = 'mock-audit-' + uid()
        await apply_status(db, log, 'no-answer', {})
    else:
        callback = f'{s.public_base_url}/api/audit/twilio-status-callback?attempt={log.id}'
        client = Client(s.twilio_account_sid, s.twilio_auth_token)
        try:
            call = await asyncio.to_thread(
                client.calls.create, to=prospect.landline_phone, from_=s.twilio_from_number,
                timeout=18, twiml='<Response><Say language="it-IT">Buongiorno, grazie. Richiameremo in un altro momento.</Say><Hangup/></Response>',
                status_callback=callback, status_callback_method='POST',
                status_callback_event=['ringing', 'completed'])
            # Callback may have arrived while the provider request was pending.
            await db.refresh(log)
            log.provider_id = call.sid
            await db.commit()
        except Exception:
            await db.rollback()
            # Do not reset the claim: timeout may mean the call was accepted.
            raise HTTPException(502, 'Esito Twilio da verificare; audit bloccato per evitare duplicati')
    return {'attempt_id': log.id, 'status': log.status, 'mock': s.simulated}
