import os
import tempfile
import asyncio
from pathlib import Path
_tmp = tempfile.TemporaryDirectory()
os.environ.update(DATABASE_URL='sqlite+aiosqlite:///' + str(Path(_tmp.name) / 'test.db'), DRY_RUN='true', MOCK_MODE='true', MOCK_CALENDAR='true')
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, Session
from app.models import CallLog, Prospect, uid, now

AUTH = ('admin', 'local-development-password')
KEY = {'X-Tool-Key': 'local-development-tool-key'}

@pytest.fixture
def client():
    async def reset():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
    asyncio.run(reset())
    with TestClient(app) as c:
        yield c

def prospect(c, suffix='1'):
    body = dict(company_name='Rossi <Serramenti>', owner_name='Marco', city='Brescia', service_type='infissi', landline_phone='+39030000000' + suffix, mobile_phone='+39333000000' + suffix)
    r = c.post('/api/prospects', json=body, auth=AUTH)
    assert r.status_code == 201, r.text
    return r.json()

def demo(c, p):
    invite = c.get(f'/api/prospects/{p["id"]}/invite', auth=AUTH).json()
    body = dict(prospect_id=p['id'], token=invite['token'], mobile_phone=p['mobile_phone'], consent=True, whatsapp_consent=True)
    r = c.post('/api/demo/trigger', json=body)
    assert r.status_code == 200, r.text
    return r.json(), body

def test_full_mock_funnel(client):
    c=client
    p=prospect(c)
    assert c.post(f'/api/audit/{p["id"]}/start', auth=AUTH).status_code == 200
    listed=c.get('/api/prospects', auth=AUTH).json()[0]
    assert listed['audit_status']=='no_answer'
    assert 'non ha ricevuto risposta' in listed['generated_outreach_text']
    result,body=demo(c,p)
    assert c.post('/api/demo/trigger',json=body).status_code==409
    assert c.post('/api/tools/send-whatsapp-simulation',json={'prospect_id':p['id']},headers=KEY).json()['status']=='mock_sent'
    slot=c.post('/api/tools/check-calendar',headers=KEY).json()['slots'][0]
    booking={'prospect_id':p['id'],'preferred_slot':slot}
    booked=c.post('/api/tools/book-sales-meeting',json=booking,headers=KEY)
    assert booked.status_code==200,booked.text
    assert c.post('/api/tools/book-sales-meeting',json=booking,headers=KEY).json()['meeting_id']==booked.json()['meeting_id']
    event={'type':'post_call_transcription','data':{'conversation_id':result['conversation_id'],'transcript':[{'role':'agent','message':'Ciao'}],'metadata':{'call_duration_secs':90}}}
    assert c.post('/api/tools/post-call-webhook',json=event,headers=KEY).status_code==200
    assert c.post('/api/tools/post-call-webhook',json=event,headers=KEY).json()['status']=='already_processed'
    listed=c.get('/api/prospects',auth=AUTH).json()[0]
    assert listed['qual_status']=='meeting_booked' and listed['demo_state']=='completed'
    h=c.get(f'/api/prospects/{p["id"]}/history',auth=AUTH).json()
    assert len(h['calls'])==2 and len(h['meetings'])==1

def test_security(client):
    c=client
    assert c.get('/admin/prospects').status_code==401
    assert c.post('/api/tools/check-calendar').status_code==401
    assert c.post('/api/tools/post-call-webhook',json={}).status_code==401
    p=prospect(c)
    assert c.get(f'/prova/{p["id"]}?token=forged').status_code==403
    invite=c.get(f'/api/prospects/{p["id"]}/invite',auth=AUTH).json()
    html=c.get(invite['url']).text
    assert '&lt;Serramenti&gt;' in html and 'Rossi <Serramenti>' not in html
    assert c.get('/admin/prospects',auth=AUTH).status_code==200
    body={'prospect_id':p['id'],'token':invite['token'],'mobile_phone':'123','consent':True}
    assert c.post('/api/demo/trigger',json=body).status_code==422
    body.update(mobile_phone=p['mobile_phone'],consent=False)
    assert c.post('/api/demo/trigger',json=body).status_code==422
    assert c.post('/api/prospects',json={},auth=AUTH,headers={'Origin':'https://evil.example'}).status_code==403

def test_conflicts(client):
    c=client
    p1,p2=prospect(c),prospect(c,'2')
    demo(c,p1);demo(c,p2)
    slot=c.post('/api/tools/check-calendar',headers=KEY).json()['slots'][0]
    for p,status in [(p1,200),(p2,409)]:
        assert c.post('/api/tools/book-sales-meeting',json={'prospect_id':p['id'],'preferred_slot':slot},headers=KEY).status_code==status
    for value in ['domani','2020-01-01T09:00:00+01:00','2030-01-01T09:00:00']:
        assert c.post('/api/tools/book-sales-meeting',json={'prospect_id':p2['id'],'preferred_slot':value},headers=KEY).status_code==422

def test_whatsapp(client):
    c=client;p=prospect(c)
    body={'Body':'PROVA','From':'whatsapp:'+p['mobile_phone'],'MessageSid':'SMtest'}
    assert c.post('/api/demo/whatsapp',data=body).status_code==401
    assert c.post('/api/demo/whatsapp',data=body,headers=KEY).status_code==200
    assert c.post('/api/demo/whatsapp',data=body,headers=KEY).status_code==200
    assert len(c.get(f'/api/prospects/{p["id"]}/history',auth=AUTH).json()['calls'])==1

def test_audit_callback(client):
    c=client;p=prospect(c)
    async def setup():
        async with Session() as db:
            model=await db.get(Prospect,p['id'])
            log=CallLog(id=uid(),prospect_id=p['id'],kind='audit',provider_id='CAtest',started_at=now())
            db.add(log);model.active_audit_id=log.id;model.audit_status='starting'
            await db.commit()
            return log.id
    url='/api/audit/twilio-status-callback?attempt='+asyncio.run(setup())
    assert c.post(url,data={'CallSid':'CAtest','CallStatus':'busy'}).status_code==401
    assert c.post(url,data={'CallSid':'wrong','CallStatus':'busy'},headers=KEY).status_code==400
    for status in ['busy','completed']:
        assert c.post(url,data={'CallSid':'CAtest','CallStatus':status},headers=KEY).status_code==200
    assert c.get('/api/prospects',auth=AUTH).json()[0]['audit_status']=='busy'

def test_outbound_contract(monkeypatch):
    from app.services import elevenlabs
    from types import SimpleNamespace
    captured={}
    class FakeClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,**kwargs):
            captured.update(url=url,**kwargs)
            import httpx
            return httpx.Response(200,json={'success':True,'conversation_id':'conv_test'},request=httpx.Request('POST',url))
    monkeypatch.setattr(elevenlabs,'get_settings',lambda:SimpleNamespace(simulated=False,elevenlabs_agent_id='agent',elevenlabs_phone_number_id='phone',elevenlabs_api_key='key',timezone='Europe/Rome'))
    monkeypatch.setattr(elevenlabs.httpx,'AsyncClient',FakeClient)
    p=SimpleNamespace(id='p1',company_name='Rossi',owner_name='Marco',city='Brescia',service_type='infissi',audit_timestamp=None,mobile_phone='+393331234567')
    asyncio.run(elevenlabs.start_call(p))
    assert captured['headers']=={'xi-api-key':'key'}
    assert captured['json']['to_number']==p.mobile_phone
    assert captured['json']['conversation_initiation_client_data']['dynamic_variables']['prospect_id']=='p1'

def test_concurrent_demo_claim(client):
    from concurrent.futures import ThreadPoolExecutor
    c=client;p=prospect(c)
    token=c.get(f'/api/prospects/{p["id"]}/invite',auth=AUTH).json()['token']
    body={'prospect_id':p['id'],'token':token,'mobile_phone':p['mobile_phone'],'consent':True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:c.post('/api/demo/trigger',json=body).status_code,range(2)))
    assert sorted(results)==[200,409]
    assert len(c.get(f'/api/prospects/{p["id"]}/history',auth=AUTH).json()['calls'])==1


def test_live_webhook_signatures(client,monkeypatch):
    import hashlib,hmac,time,json
    from types import SimpleNamespace
    from app import security
    from twilio.request_validator import RequestValidator
    settings=SimpleNamespace(simulated=False,elevenlabs_webhook_secret='test-secret',twilio_auth_token='twilio-test-token',public_base_url='http://testserver')
    monkeypatch.setattr(security,'get_settings',lambda:settings)
    raw=json.dumps({'type':'post_call_audio','data':{}}).encode()
    timestamp=str(int(time.time()))
    signature=hmac.new(b'test-secret',timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    headers={'elevenlabs-signature':f't={timestamp},v0={signature}','content-type':'application/json'}
    assert client.post('/api/tools/post-call-webhook',content=raw,headers=headers).status_code==200
    assert client.post('/api/tools/post-call-webhook',content=raw+b' ',headers=headers).status_code==403
    old=str(int(time.time())-600)
    sig=hmac.new(b'test-secret',old.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    assert client.post('/api/tools/post-call-webhook',content=raw,headers={'elevenlabs-signature':f't={old},v0={sig}'}).status_code==403
    form={'Body':'ciao','From':'whatsapp:+393331234567'}
    url='http://testserver/api/demo/whatsapp'
    sig=RequestValidator(settings.twilio_auth_token).compute_signature(url,form)
    assert client.post('/api/demo/whatsapp',data=form,headers={'X-Twilio-Signature':sig}).status_code==200
    assert client.post('/api/demo/whatsapp',data=form,headers={'X-Twilio-Signature':'forged'}).status_code==403


def test_duplicate_phone_does_not_consume_invite(client):
    c=client;p1,p2=prospect(c),prospect(c,'2')
    token=c.get(f'/api/prospects/{p2["id"]}/invite',auth=AUTH).json()['token']
    body={'prospect_id':p2['id'],'token':token,'mobile_phone':p1['mobile_phone'],'consent':True}
    assert c.post('/api/demo/trigger',json=body).status_code==409
    body['mobile_phone']=p2['mobile_phone']
    assert c.post('/api/demo/trigger',json=body).status_code==200


def test_calendar_provider_failure_preserves_reservation(client,monkeypatch):
    from app.services import calendar
    c=client;p=prospect(c);demo(c,p)
    slot=c.post('/api/tools/check-calendar',headers=KEY).json()['slots'][0]
    body={'prospect_id':p['id'],'preferred_slot':slot}
    async def fail(*args):raise TimeoutError()
    monkeypatch.setattr(calendar,'create_event',fail)
    assert c.post('/api/tools/book-sales-meeting',json=body,headers=KEY).status_code==502
    async def recover(meeting,prospect):return 'recovered-event'
    monkeypatch.setattr(calendar,'create_event',recover)
    assert c.post('/api/tools/book-sales-meeting',json=body,headers=KEY).status_code==200
    h=c.get(f'/api/prospects/{p["id"]}/history',auth=AUTH).json()
    assert len(h['meetings'])==1 and h['meetings'][0]['event_id']=='recovered-event'
