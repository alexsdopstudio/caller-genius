import hashlib
import hmac
import time
from fastapi import Depends, HTTPException, Request, Header
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from twilio.request_validator import RequestValidator
from app.config import get_settings

basic = HTTPBasic()


def admin(credentials: HTTPBasicCredentials = Depends(basic)):
    s = get_settings()
    valid_user = hmac.compare_digest(credentials.username.encode(), s.admin_user.encode())
    valid_password = hmac.compare_digest(credentials.password.encode(), s.admin_password.encode())
    if not (valid_user and valid_password):
        raise HTTPException(401, 'Credenziali non valide', headers={'WWW-Authenticate': 'Basic'})


def tool_auth(x_tool_key: str = Header(default='')):
    if not hmac.compare_digest(x_tool_key, get_settings().tool_api_key):
        raise HTTPException(401, 'Invalid tool key')


def serializer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt='demo-link-v1')


def magic_token(prospect):
    return serializer().dumps({'id': prospect.id, 'nonce': prospect.demo_nonce})


def check_magic(prospect, token):
    try:
        data = serializer().loads(token, max_age=get_settings().magic_link_max_age)
    except (BadSignature, SignatureExpired):
        raise HTTPException(403, 'Link scaduto o non valido')
    if data != {'id': prospect.id, 'nonce': prospect.demo_nonce}:
        raise HTTPException(403, 'Link non valido')


async def twilio_form(request: Request):
    s = get_settings()
    form = await request.form()
    # Mock callbacks require the tool secret too; signatures are never bypassed publicly.
    if s.simulated:
        tool_auth(request.headers.get('x-tool-key', ''))
    else:
        url = s.public_base_url + request.url.path
        if request.url.query:
            url += '?' + request.url.query
        if not RequestValidator(s.twilio_auth_token).validate(url, form, request.headers.get('x-twilio-signature', '')):
            raise HTTPException(403, 'Invalid Twilio signature')
    return form


async def verify_elevenlabs(request: Request):
    s = get_settings()
    body = await request.body()
    if s.simulated:
        tool_auth(request.headers.get('x-tool-key', ''))
        return
    try:
        parts = [item.strip().split('=', 1) for item in request.headers.get('elevenlabs-signature', '').split(',')]
        stamp = next(value for key, value in parts if key == 't')
        signatures = [value for key, value in parts if key == 'v0']
        if abs(time.time() - int(stamp)) > 300:
            raise ValueError()
        expected = hmac.new(s.elevenlabs_webhook_secret.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for value in signatures):
            raise ValueError()
    except (ValueError, StopIteration):
        raise HTTPException(403, 'Invalid ElevenLabs signature')
