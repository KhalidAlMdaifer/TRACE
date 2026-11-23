-- M5: a flight day knows the job fetching it, and keeps the integrity filter's counts.
ALTER TABLE flight_days ADD COLUMN job_id TEXT;
ALTER TABLE flight_days ADD COLUMN stats TEXT;         -- JSON: aircraft, rows, dropped by reason, rows_dropped_pct
ALTER TABLE flight_days ADD COLUMN error TEXT;
