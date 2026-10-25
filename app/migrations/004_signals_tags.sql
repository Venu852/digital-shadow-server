-- Rows from before the six-signal contract (no "timing" level) are legacy demo data
DELETE FROM daily_summaries WHERE levels_json NOT LIKE '%"timing"%';

-- New context tags; old tags map to their nearest new one
CREATE TABLE team_settings_new (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
    human_review INTEGER NOT NULL DEFAULT 1 CHECK(human_review IN (0, 1)),
    context_tag TEXT NOT NULL DEFAULT 'None'
        CHECK(context_tag IN ('None', 'Exam week', 'Travel', 'Holiday or break', 'Busy period', 'New routine')),
    updated_at TEXT NOT NULL
);

INSERT INTO team_settings_new (team_id, human_review, context_tag, updated_at)
SELECT team_id, human_review,
       CASE context_tag
           WHEN 'Deadline crunch' THEN 'Busy period'
           WHEN 'Product launch' THEN 'New routine'
           ELSE context_tag
       END,
       updated_at
FROM team_settings;

DROP TABLE team_settings;
ALTER TABLE team_settings_new RENAME TO team_settings;
