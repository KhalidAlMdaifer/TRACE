-- docs/05-architecture.md, section 4. Additions to that schema are marked "added".
CREATE TABLE users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'analyst', created_at TEXT NOT NULL);

CREATE TABLE cases (
  id TEXT PRIMARY KEY,                 -- ULID
  case_ref TEXT, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
  status TEXT NOT NULL,                -- draft | triaged | searching | done | failed
  pack_id TEXT NOT NULL DEFAULT 'uae',
  date_local TEXT,                     -- YYYY-MM-DD
  time_ranges TEXT,                    -- JSON [["12:00","17:00"]], null = whole day
  region_ids TEXT,                     -- JSON ["dubai"], null = whole pack
  custom_bbox TEXT,                    -- JSON [lat_min, lat_max, lon_min, lon_max] or null
  temperature_c REAL, temperature_source TEXT);

CREATE TABLE media (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  filename TEXT NOT NULL, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,
  duration_s REAL, path TEXT NOT NULL, spectrogram_path TEXT, created_at TEXT NOT NULL);

CREATE TABLE events (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id),
  source TEXT NOT NULL,                -- detect | analyst
  status TEXT NOT NULL,                -- proposed | confirmed | rejected
  t_start REAL NOT NULL, t_end REAL NOT NULL, f_lo REAL NOT NULL, f_hi REAL NOT NULL,   -- the box as drawn; fit() widens it
  harmonics INTEGER NOT NULL DEFAULT 1,
  fit TEXT,                            -- JSON of EventFit.to_dict(): detect's coarse fit, then the editor preview; display only
  curve TEXT,                          -- added: JSON [[t, hz], ...] of that fit, so the api never needs dopplertrack to draw it
  fit_temperature_c REAL,              -- the temperature that fit used
  score REAL, burst REAL, created_at TEXT NOT NULL);
CREATE INDEX events_case ON events(case_id);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY, case_id TEXT REFERENCES cases(id),
  kind TEXT NOT NULL,                  -- triage | fetch | search
  status TEXT NOT NULL,                -- queued | running | done | failed | cancelled
  stage TEXT, progress REAL, params TEXT, error TEXT, pid INTEGER,
  cancel_requested TEXT,               -- added: null | cancel | truncate (stop a triage job that is only detecting, and call it done)
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE INDEX jobs_status ON jobs(status);
CREATE INDEX jobs_case ON jobs(case_id);

CREATE TABLE job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
  case_id TEXT,                        -- added: the stream is per case
  ts TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX job_events_case ON job_events(case_id, id);

CREATE TABLE results (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), job_id TEXT NOT NULL,
  state TEXT NOT NULL,                 -- located | candidates | outside | not_locatable
  verdict TEXT, p REAL, strength INTEGER, band TEXT,
  lat REAL, lon REAL, radius_m REAL,
  payload TEXT NOT NULL,               -- full result JSON (section 7)
  created_at TEXT NOT NULL);
CREATE INDEX results_case ON results(case_id);

CREATE TABLE flight_days (
  pack_id TEXT NOT NULL, utc_date TEXT NOT NULL, status TEXT NOT NULL,   -- missing | fetching | ready | failed
  n_traces INTEGER, n_prop INTEGER, rows_dropped_pct REAL, traces_path TEXT, source_tag TEXT, fetched_at TEXT,
  PRIMARY KEY (pack_id, utc_date));

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id INTEGER, case_id TEXT,
  action TEXT NOT NULL, detail TEXT, ip TEXT);
CREATE INDEX audit_user ON audit_log(user_id, action, ts);
