-- Відправка запису розмови адмінам (окремим повідомленням після дзвінка)
ALTER TABLE call_logs
    ADD COLUMN send_recording     BOOLEAN NOT NULL DEFAULT false,  -- є заявка або потрібен передзвін
    ADD COLUMN recording_sent_at  TIMESTAMPTZ,
    ADD COLUMN recording_attempts SMALLINT NOT NULL DEFAULT 0;     -- ліміт спроб, щоб не крутити вічно

CREATE INDEX idx_calls_recording_pending ON call_logs (created_at)
    WHERE send_recording AND recording_sent_at IS NULL;
