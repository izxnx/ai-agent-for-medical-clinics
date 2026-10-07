from __future__ import annotations
import re
import unicodedata
from pydantic import BaseModel, ConfigDict, field_validator

class BookingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='ignore', validate_default=True)
    patient_name: str
    service_or_specialty: str
    city_or_branch: str
    is_urgent: bool = False
    patient_phone: str = ''
    preferred_date: str = ''
    preferred_time: str = ''
    symptoms_summary: str = ''
    urgent_reason: str = ''

    @field_validator('patient_name')
    @classmethod
    def validate_name(cls, value):
        value = _clean(value, 120)
        if not value:
            raise ValueError('must not be empty')
        return value

    @field_validator('service_or_specialty','city_or_branch')
    @classmethod
    def required_text(cls, value):
        value = _clean(value, 200)
        if not value:
            raise ValueError('must not be empty')
        return value

    @field_validator('patient_phone')
    @classmethod
    def normalize_phone(cls, value, info):
        value = _clean(value, 40)
        if not value:
            if not info.data.get('is_urgent', False) and info.data.get('service_or_specialty') != 'Передзвін':
                raise ValueError('patient_phone is required')
            return ''
        digits = re.sub(r'\D', '', value)
        if digits.startswith('380') and len(digits)==12:
            pass
        elif digits.startswith('0') and len(digits)==10:
            digits='38'+digits
        elif len(digits)==9 and digits[0] in '345679':
            digits='380'+digits
        else:
            raise ValueError('invalid Ukrainian phone number')
        if not digits.startswith('380') or len(digits)!=12:
            raise ValueError('invalid Ukrainian phone number')
        return '+'+digits

    @field_validator('preferred_date','preferred_time','symptoms_summary','urgent_reason')
    @classmethod
    def optional_text(cls, value, info):
        limits={'preferred_date':120,'preferred_time':120,'symptoms_summary':1000,'urgent_reason':500}
        return _clean(value,limits[info.field_name])

def _clean(value: str, limit: int) -> str:
    value=''.join(ch for ch in value if unicodedata.category(ch) not in {'Cc','Cf'})
    value=' '.join(value.strip().split())
    if len(value)>limit:
        raise ValueError(f'must be at most {limit} characters')
    return value
