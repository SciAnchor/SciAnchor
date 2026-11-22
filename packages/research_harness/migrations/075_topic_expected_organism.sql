-- BUG-012: declare a topic's expected organism so cross-species / cross-model
-- evidence (e.g. human DVT topic pulling mouse vein-wall or CTEPH data) can be
-- flagged as support-only instead of silently passing the validation gate.
-- Empty = unset (check is opt-in). Conventional values: 'human', 'mouse', ...
ALTER TABLE topics ADD COLUMN expected_organism TEXT DEFAULT '';
