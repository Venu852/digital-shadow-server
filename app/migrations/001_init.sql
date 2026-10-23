CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('individual', 'manager')),
    created_at TEXT NOT NULL
);

CREATE TABLE teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    manager_id INTEGER NOT NULL REFERENCES accounts(id),
    invite_code TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE memberships (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    joined_at TEXT NOT NULL,
    PRIMARY KEY(team_id, account_id)
);
