-- Короткі claim leases дають змогу робити HTTP-запити поза транзакцією БД.
ALTER TABLE booking_requests
    ADD COLUMN notify_claim_token TEXT,
    ADD COLUMN notify_claimed_until TIMESTAMPTZ;

ALTER TABLE call_logs
    ADD COLUMN notify_claim_token TEXT,
    ADD COLUMN notify_claimed_until TIMESTAMPTZ,
    ADD COLUMN recording_claim_token TEXT,
    ADD COLUMN recording_claimed_until TIMESTAMPTZ;
