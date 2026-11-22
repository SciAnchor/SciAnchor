-- BUG-015: persist the "run all computation on the remote server only"
-- constraint as a durable per-topic config instead of chat/file prose, so
-- agents cannot silently fall back to local execution. Empty = unset;
-- conventional values: 'remote_only', 'local_ok', or an explicit host label.
ALTER TABLE topics ADD COLUMN compute_location TEXT DEFAULT '';
