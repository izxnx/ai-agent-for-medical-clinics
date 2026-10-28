-- Звіт після дзвінка: підсумок і поля з Retell Post-Call Analysis (подія call_analyzed).
ALTER TABLE call_logs
    ADD COLUMN call_summary TEXT,
    ADD COLUMN analysis     JSONB,
    ADD COLUMN analyzed_at  TIMESTAMPTZ;

-- Старі дзвінки не мають потрапити в нові звіти повторно.
UPDATE call_logs SET admin_notified_at = now() WHERE admin_notified_at IS NULL;
