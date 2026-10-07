from datetime import datetime, timezone
from app import messages

def row(**kw):
    base={'id':1,'patient_name':'Тест & Пацієнт','patient_phone':'+380000000000','service_or_specialty':'Консультація','city_or_branch':'Львів','preferred_date':'Не вказано','preferred_time':'перша половина дня','symptoms_summary':'Вигадана скарга','is_urgent':False,'urgent_reason':'','created_at':datetime.now(timezone.utc),'caller_phone':'+380000000000','transcript':'User: вигаданий дзвінок','booking_urgent':False,'booking_ids':[]}
    base.update(kw); return base

def test_format_booking_and_html_escape():
    text=messages.format_booking(row())
    assert '&amp;' in text and '<b>Нова заявка' in text

def test_urgent_format_and_call_without_booking():
    assert 'ВАЖЛИВЕ' in messages.format_booking(row(is_urgent=True))
    assert 'Дзвінок без заявки' in messages.format_call(row())
    assert 'ВАЖЛИВЕ' in messages.format_call(row(is_urgent=True,urgent_reason='вигадана ознака'))

def test_caption_and_truncation_are_bounded_and_entities_intact():
    assert len(messages.recording_caption(row(caller_phone='<'*5000))) <= 1024
    from html import escape
    text=messages._truncate_message('<b>'+escape('&'*5000)+'</b>',4096)
    assert len(text) <= 4096
    import re
    assert not re.search(r'&(?!amp;|lt;|gt;|quot;|#x27;)', text)
    assert len(messages.format_booking(row(symptoms_summary='<'*5000))) <= 4096
