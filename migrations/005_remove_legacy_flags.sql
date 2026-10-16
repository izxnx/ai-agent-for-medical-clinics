-- Remove obsolete internal flags while preserving every booking and call record.
DROP INDEX IF EXISTS idx_booking_requests_pending;

ALTER TABLE booking_requests
    DROP COLUMN IF EXISTS urgent_reason,
    DROP COLUMN IF EXISTS is_urgent;

ALTER TABLE call_logs
    DROP COLUMN IF EXISTS urgent_reason,
    DROP COLUMN IF EXISTS is_urgent;
