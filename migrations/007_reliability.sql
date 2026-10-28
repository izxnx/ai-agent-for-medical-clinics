-- Caller ID (номер, з якого дзвонили) окремо від підтвердженого пацієнтом контакту.
ALTER TABLE call_logs ADD COLUMN caller_id TEXT;

-- Повтори запису розмови з наростаючим інтервалом і явним статусом остаточної невдачі.
ALTER TABLE call_logs
    ADD COLUMN recording_next_attempt_at TIMESTAMPTZ,
    ADD COLUMN recording_last_error      TEXT,
    ADD COLUMN recording_failed_at       TIMESTAMPTZ;

-- Записи, які вже вичерпали старий ліміт у 8 спроб, вважаємо остаточно ненадісланими.
UPDATE call_logs SET recording_failed_at = now()
WHERE send_recording AND recording_sent_at IS NULL AND recording_attempts >= 8;
