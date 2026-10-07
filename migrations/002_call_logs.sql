CREATE TABLE IF NOT EXISTS call_logs (
    id BIGSERIAL PRIMARY KEY,
    call_id TEXT UNIQUE NOT NULL,
    caller_phone TEXT,
    ended_reason TEXT,
    transcript TEXT,
    recording_url TEXT,
    needs_callback BOOLEAN NOT NULL DEFAULT false,
    is_urgent BOOLEAN NOT NULL DEFAULT false,
    urgent_reason TEXT,
    admin_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
