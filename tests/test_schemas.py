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

@pytest.mark.parametrize("changes,field", [({"patient_name":"  "},"patient_name"),("phone", "patient_phone"),("city_or_branch", "city_or_branch"),("service_or_specialty", "service_or_specialty")])
def test_invalid_fields(changes,field):
    values=payload()
    if changes=="phone": values["patient_phone"]="123"
    else: values[changes]=""
    with pytest.raises(ValidationError): BookingRequest(**values)
