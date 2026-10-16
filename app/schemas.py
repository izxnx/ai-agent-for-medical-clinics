from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, field_validator


ALLOWED_SERVICES = (
    "Консультація флеболога",
    "Консультація проктолога",
    "УЗД судин",
    "УЗД серця",
    "Лазерне лікування вен",
    "Склеротерапія",
    "Біоклей",
    "Підбір трикотажу",
    "Передзвін",
)
_SERVICES_BY_CASEFOLD = {service.casefold(): service for service in ALLOWED_SERVICES}


class BookingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='ignore', validate_default=True)
    patient_name: str
    service_or_specialty: str
    city_or_branch: str
    patient_phone: str = ''
    preferred_date: str
    preferred_time: str
    symptoms_summary: str

    @field_validator('patient_name')
    @classmethod
    def validate_name(cls, value):
        value = _clean(value, 120)
        if not value:
            raise ValueError('must not be empty')
        return value

    @field_validator('service_or_specialty')
    @classmethod
    def validate_service(cls, value):
        value = _clean(value, 200)
        if not value:
            raise ValueError('must not be empty')
        service = _SERVICES_BY_CASEFOLD.get(value.casefold())
        if service is None:
            raise ValueError('choose an available clinic service or Передзвін')
        return service

    @field_validator('city_or_branch')
    @classmethod
    def validate_city_or_branch(cls, value):
        value = _clean(value, 200)
        if not value:
            raise ValueError('must not be empty')
        return value

    @field_validator('patient_phone')
    @classmethod
    def normalize_phone(cls, value, info):
        value = _clean(value, 40)
        if not value:
            if info.data.get('service_or_specialty') != 'Передзвін':
                raise ValueError('patient_phone is required')
            return ''
        if not re.fullmatch(r'\+?[\d\s().-]+', value) or (value.count('+') and not value.startswith('+')):
            raise ValueError('invalid Ukrainian phone number')
        digits = re.sub(r'\D', '', value)
        if digits.startswith('380') and len(digits)==12:
            pass
        elif digits.startswith('0') and len(digits)==10:
            digits='38'+digits
        elif len(digits)==9 and digits[0] in '3456789':
            digits='380'+digits
        else:
            raise ValueError('invalid Ukrainian phone number')
        if not digits.startswith('380') or len(digits)!=12:
            raise ValueError('invalid Ukrainian phone number')
        return '+'+digits

    @field_validator('preferred_date', 'preferred_time', 'symptoms_summary')
    @classmethod
    def validate_confirmed_fields(cls, value, info):
        limits = {'preferred_date': 120, 'preferred_time': 120, 'symptoms_summary': 1000}
        value = _clean(value, limits[info.field_name])
        if not value:
            raise ValueError('must not be empty; use Не вказано when unavailable')
        if info.field_name == 'preferred_date' and value.casefold() != 'не вказано':
            raise ValueError('preferred_date must be Не вказано')
        if info.field_name == 'preferred_time':
            allowed = {'перша половина дня', 'друга половина дня', 'не вказано'}
            if value.casefold() not in allowed:
                raise ValueError('choose a supported time preference or Не вказано')
            normalized_times = {
                'перша половина дня': 'перша половина дня',
                'друга половина дня': 'друга половина дня',
                'не вказано': 'Не вказано',
            }
            return normalized_times[value.casefold()]
        if info.field_name == 'preferred_date':
            return 'Не вказано'
        return value

def _clean(value: str, limit: int) -> str:
    value=''.join(ch for ch in value if unicodedata.category(ch) not in {'Cc','Cf'})
    value=' '.join(value.strip().split())
    if len(value)>limit:
        raise ValueError(f'must be at most {limit} characters')
    return value
