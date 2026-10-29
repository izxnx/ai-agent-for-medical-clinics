-- Тип дзвінка (web_call = тестовий з Retell Dashboard) і дані, які агент зібрав у submit_booking_request.
ALTER TABLE call_logs
    ADD COLUMN call_type TEXT,
    ADD COLUMN collected JSONB;
