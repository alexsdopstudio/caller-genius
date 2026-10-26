from functools import lru_cache
from zoneinfo import ZoneInfo
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    dry_run: bool = True
    mock_mode: bool = True
    mock_calendar: bool = True
    database_url: str = 'sqlite+aiosqlite:///./voice_funnel.db'
    public_base_url: str = 'http://localhost:8000'
    timezone: str = 'Europe/Rome'
    admin_user: str = 'admin'
    admin_password: str = 'local-development-password'
    secret_key: str = 'local-development-signing-key-change-me'
    tool_api_key: str = 'local-development-tool-key'
    magic_link_max_age: int = 604800
    twilio_account_sid: str = ''
    twilio_auth_token: str = ''
    twilio_from_number: str = ''
    twilio_whatsapp_from: str = ''
    elevenlabs_api_key: str = ''
    elevenlabs_agent_id: str = ''
    elevenlabs_phone_number_id: str = ''
    elevenlabs_webhook_secret: str = ''
    google_calendar_id: str = ''
    google_service_account_file: str = ''
    google_oauth_file: str = ''
    calendar_start_hour: int = 9
    calendar_end_hour: int = 18
    meeting_minutes: int = 10

    @property
    def simulated(self):
        return self.dry_run or self.mock_mode

    @model_validator(mode='after')
    def validate_settings(self):
        ZoneInfo(self.timezone)
        if not 0 <= self.calendar_start_hour < self.calendar_end_hour <= 24:
            raise ValueError('Invalid calendar business hours')
        if not 1 <= self.meeting_minutes <= 60:
            raise ValueError('MEETING_MINUTES must be 1..60')
        if self.database_url.startswith('postgresql://'):
            self.database_url = self.database_url.replace('postgresql://', 'postgresql+asyncpg://', 1)
        if not self.simulated:
            required = ['twilio_account_sid', 'twilio_auth_token', 'twilio_from_number',
                        'twilio_whatsapp_from', 'elevenlabs_api_key', 'elevenlabs_agent_id',
                        'elevenlabs_phone_number_id', 'elevenlabs_webhook_secret']
            for key in required:
                if not getattr(self, key):
                    raise ValueError(f'Missing live setting: {key}')
            for key in ['admin_password', 'secret_key', 'tool_api_key']:
                if getattr(self, key).startswith('local-development') or len(getattr(self, key)) < 24:
                    raise ValueError(f'Use a random secret of at least 24 characters: {key}')
            if not self.public_base_url.startswith('https://'):
                raise ValueError('Live mode requires PUBLIC_BASE_URL=https://...')
        if not (self.simulated or self.mock_calendar):
            if not self.google_calendar_id or not (self.google_service_account_file or self.google_oauth_file):
                raise ValueError('Google Calendar credentials and calendar ID required')
        self.public_base_url = self.public_base_url.rstrip('/')
        return self


@lru_cache
def get_settings():
    return Settings()
