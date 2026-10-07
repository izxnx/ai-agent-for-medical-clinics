CREATE TABLE IF NOT EXISTS booking_requests (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE NOT NULL,
    call_id TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    patient_phone TEXT NOT NULL DEFAULT '',
    service_or_specialty TEXT NOT NULL,
    city_or_branch TEXT NOT NULL,
    preferred_date TEXT,
    preferred_time TEXT,
    symptoms_summary TEXT,
    is_urgent BOOLEAN NOT NULL DEFAULT false,
    urgent_reason TEXT,
    admin_notified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_booking_requests_call_id ON booking_requests(call_id);
CREATE INDEX IF NOT EXISTS idx_booking_requests_pending ON booking_requests(is_urgent DESC, created_at)
    WHERE admin_notified_at IS NULL;
