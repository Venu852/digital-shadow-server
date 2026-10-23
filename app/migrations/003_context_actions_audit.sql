CREATE TABLE team_settings (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
    human_review INTEGER NOT NULL DEFAULT 1 CHECK(human_review IN (0, 1)),
    context_tag TEXT NOT NULL DEFAULT 'None'
        CHECK(context_tag IN ('None', 'Exam week', 'Deadline crunch', 'Product launch', 'Holiday or break')),
    updated_at TEXT NOT NULL
);

CREATE TABLE action_decisions (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('approved', 'dismissed')),
    decided_by INTEGER NOT NULL REFERENCES accounts(id),
    decided_at TEXT NOT NULL,
    PRIMARY KEY(team_id, day)
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    actor_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
    detail TEXT
);
