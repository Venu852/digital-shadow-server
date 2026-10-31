-- The signal a suggestion pointed to when the coordinator decided on it, so impact checks
-- and group updates never change afterwards. NULL means it could not be worked out.
ALTER TABLE action_decisions ADD COLUMN signal TEXT;
