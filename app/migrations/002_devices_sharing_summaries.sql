CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at TEXT
);

CREATE TABLE sharing_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    level TEXT NOT NULL CHECK(level IN ('nothing', 'team_totals', 'my_trend')),
    changed_at TEXT NOT NULL
);

CREATE TABLE daily_summaries (
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    drift INTEGER NOT NULL CHECK(drift BETWEEN 0 AND 100),
    levels_json TEXT NOT NULL,
    confidence INTEGER CHECK(confidence BETWEEN 0 AND 100),
    baseline TEXT NOT NULL CHECK(baseline IN ('calibrating', 'established')),
    forecast_json TEXT,
    unusual_hours_json TEXT,
    tz TEXT,
    received_at TEXT NOT NULL,
    PRIMARY KEY(device_id, day)
);

CREATE INDEX idx_daily_summaries_day ON daily_summaries(day);
