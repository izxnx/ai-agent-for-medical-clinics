import pytest
from pydantic import ValidationError
from app.schemas import BookingRequest

def payload(**overrides):
    return {"patient_name":" Тестовий Пацієнт ","patient_phone":"(099) 123-45-67","service_or_specialty":"Консультація флеболога","city_or_branch":"Львів",**overrides}

def test_phone_normalization_and_trim():
    assert BookingRequest(**payload()).patient_phone == "+380991234567"
    for phone in ("0991234567", "380991234567", "+380 99 123 45 67"):
        assert BookingRequest(**payload(patient_phone=phone)).patient_phone == "+380991234567"

def test_placeholders_and_urgent_without_name_phone():
    item=BookingRequest(**payload(patient_name="Не вказано",patient_phone="",is_urgent=True))
    assert item.patient_name == "Не вказано"
    assert BookingRequest(**payload(patient_name="Не назвався")).patient_name == "Не назвався"

def test_empty_phone_allowed_callback_or_urgent():
    BookingRequest(**payload(patient_phone="",service_or_specialty="Передзвін"))
    BookingRequest(**payload(patient_phone="",is_urgent=True))

@pytest.mark.parametrize("field,value", [("patient_name","  "),("patient_phone","123"),("city_or_branch",""),("service_or_specialty","")])
def test_invalid_fields(field,value):
    values=payload(); values[field]=value
    with pytest.raises(ValidationError) as err: BookingRequest(**values)
    assert err.value.errors()[0]['loc']==(field,)


def test_control_characters_removed_and_limits_enforced():
    value=BookingRequest(**payload(patient_name='Тест\nовий'))
    assert value.patient_name=='Тестовий'
    with pytest.raises(ValidationError) as err:
        BookingRequest(**payload(symptoms_summary='x'*1001))
    assert err.value.errors()[0]['loc']==('symptoms_summary',)


def test_omitted_phone_requires_phone_field():
    values=payload(); values.pop('patient_phone')
    with pytest.raises(ValidationError) as err:
        BookingRequest(**values)
    assert err.value.errors()[0]['loc']==('patient_phone',)
