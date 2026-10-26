import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.models import Meeting, now, uid
from app.services.twilio_audit import utc
from app.services.messaging import send_whatsapp

booking_lock = asyncio.Lock()


def google():
    s = get_settings()
    scopes = ['https://www.googleapis.com/auth/calendar']
    if s.google_oauth_file:
        credentials = Credentials.from_authorized_user_file(s.google_oauth_file, scopes=scopes)
    else:
        credentials = service_account.Credentials.from_service_account_file(s.google_service_account_file, scopes=scopes)
    return build('calendar', 'v3', credentials=credentials, cache_discovery=False)


def candidates():
    s = get_settings()
    tz = ZoneInfo(s.timezone)
    current = now()
    for offset in range(15):
        day = current.astimezone(tz).date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        start = datetime(day.year, day.month, day.day, s.calendar_start_hour, tzinfo=tz)
        end = start.replace(hour=0) + timedelta(hours=s.calendar_end_hour)
        while start + timedelta(minutes=s.meeting_minutes) <= end:
            if start > current + timedelta(minutes=30):
                yield start
            start += timedelta(minutes=s.meeting_minutes)


async def busy_intervals(db):
    s = get_settings()
    meetings = (await db.scalars(select(Meeting))).all()
    busy = [(utc(m.start_at), utc(m.end_at)) for m in meetings]
    if s.simulated or s.mock_calendar:
        return busy
    def fetch():
        with google() as api:
            result = api.freebusy().query(body={
                'timeMin': now().isoformat(), 'timeMax': (now() + timedelta(days=16)).isoformat(),
                'timeZone': s.timezone, 'items': [{'id': s.google_calendar_id}],
            }).execute()
        calendar = result.get('calendars', {}).get(s.google_calendar_id, {})
        if calendar.get('errors') or 'busy' not in calendar:
            raise ValueError('Calendar unavailable')
        return [(datetime.fromisoformat(x['start']), datetime.fromisoformat(x['end'])) for x in calendar['busy']]
    try:
        busy.extend(await asyncio.to_thread(fetch))
    except Exception:
        raise HTTPException(502, 'Impossibile verificare le disponibilità')
    return busy


async def availability(db):
    s = get_settings()
    busy = await busy_intervals(db)
    slots = []
    for start in candidates():
        end = start + timedelta(minutes=s.meeting_minutes)
        if not any(start < b and end > a for a, b in busy):
            slots.append(start.isoformat())
        if len(slots) == 2:
            break
    spoken = ' oppure '.join(datetime.fromisoformat(x).strftime('il %d/%m alle %H:%M') for x in slots)
    return {'slots': slots, 'timezone': s.timezone, 'message': spoken or 'Nessuna disponibilità nei prossimi quindici giorni.'}


async def create_event(meeting, prospect):
    s = get_settings()
    if s.simulated or s.mock_calendar:
        return 'mock-' + meeting.id
    event_id = meeting.id.replace('-', '')
    def insert():
        with google() as api:
            # Deterministic ID permits recovery after a successful insert whose response was lost.
            try:
                return api.events().get(calendarId=s.google_calendar_id, eventId=event_id).execute()['id']
            except HttpError as exc:
                if exc.resp.status != 404:
                    raise
            body = {
                'id': event_id, 'summary': f'Demo AI — {prospect.company_name}',
                'description': f'Call con {prospect.owner_name}. Prospect {prospect.id}. Email: {meeting.prospect_email or "non fornita"}',
                'start': {'dateTime': utc(meeting.start_at).isoformat(), 'timeZone': s.timezone},
                'end': {'dateTime': utc(meeting.end_at).isoformat(), 'timeZone': s.timezone},
            }
            # Service accounts cannot invite attendees without domain-wide delegation.
            if s.google_oauth_file and meeting.prospect_email:
                body['attendees'] = [{'email': meeting.prospect_email}]
            try:
                return api.events().insert(calendarId=s.google_calendar_id, body=body,
                                           sendUpdates='all' if 'attendees' in body else 'none').execute()['id']
            except HttpError as exc:
                if exc.resp.status == 409:
                    return api.events().get(calendarId=s.google_calendar_id, eventId=event_id).execute()['id']
                raise
    return await asyncio.to_thread(insert)


async def book(db, prospect, body):
    s = get_settings()
    start = body.preferred_slot.astimezone(timezone.utc)
    async with booking_lock:
        meeting = await db.scalar(select(Meeting).where(Meeting.prospect_id == prospect.id))
        if meeting and utc(meeting.start_at) != start:
            raise HTTPException(409, 'Esiste già una prenotazione per questo prospect')
        if not meeting:
            # Accept only the advertised business grid; never guess dates from free text.
            if start not in list(candidates()):
                raise HTTPException(422, 'Scegli uno slot futuro restituito da check-calendar')
            end = start + timedelta(minutes=s.meeting_minutes)
            busy = await busy_intervals(db)
            if any(start < b and end > a for a, b in busy):
                raise HTTPException(409, 'Slot non più disponibile; cerca altri orari')
            meeting = Meeting(id=uid(), prospect_id=prospect.id, start_at=start, end_at=end,
                              prospect_email=str(body.prospect_email) if body.prospect_email else None)
            db.add(meeting)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                raise HTTPException(409, 'Slot appena prenotato; cerca altri orari')
        if meeting.status != 'confirmed':
            try:
                meeting.event_id = await create_event(meeting, prospect)
            except Exception:
                raise HTTPException(502, 'Prenotazione da verificare; ripetere solo lo stesso slot per riconciliare')
            meeting.status = 'confirmed'
            prospect.qual_status = 'meeting_booked'
            await db.commit()
        if meeting.notification_status == 'not_sent':
            # Claim before sending. An uncertain send is never silently retried.
            meeting.notification_status = 'sending'
            await db.commit()
            local = start.astimezone(ZoneInfo(s.timezone)).strftime('%d/%m/%Y alle %H:%M')
            try:
                meeting.notification_status = await send_whatsapp(prospect, f'Appuntamento con Alessandro confermato: {local} ({s.timezone}), durata {s.meeting_minutes} minuti.')
            except Exception:
                meeting.notification_status = 'unknown'
            await db.commit()
        return {'status': 'success', 'meeting_id': meeting.id,
                'preferred_slot': start.isoformat(), 'notification_status': meeting.notification_status,
                'message': 'Appuntamento confermato.'}
