# State Cleanup — One Canonical Database

> Companion to `docs/TOPIC_LIFECYCLE.md` §1. Run this when `rh doctor` reports a
> `state_trees` warning (more than one non-empty `pool.db`, an unpinned project,
> or resolution falling through to `~/.research-harness`).

## Why this matters

RH resolves its database from (in order): `--db` flag → `RESEARCH_HARNESS_DB_PATH`
env → project `.research-harness/config.json` → project default → global
`~/.research-harness/pool.db`. Without a pinned config, the choice depends on the
process working directory, and sessions started outside the checkout silently
create a *second* database in the home directory ("cwd drift"). Checkpoints
follow the effective DB (`default_state_dir`), so a stray DB also means stray
checkpoints.

## Procedure

1. **Pin the canonical DB** (writes `.research-harness/config.json`):

   ```bash
   cd <checkout>
   rh config init
   rh doctor --json | python3 -c "import json,sys; print([c for c in json.load(sys.stdin) if c['check']=='config'][0]['source'])"
   # expect: project-config
   ```

2. **Quarantine stray databases** — rename, never delete; topics inside remain
   recoverable and can be merged later if needed:

   ```bash
   ls -lh ~/.research-harness/pool.db*      # inspect first
   mv ~/.research-harness/pool.db ~/.research-harness/pool.db.quarantined-$(date +%Y%m%d)
   # include WAL/SHM side files when present:
   for suffix in -wal -shm; do
     [ -f ~/.research-harness/pool.db$suffix ] && \
       mv ~/.research-harness/pool.db$suffix ~/.research-harness/pool.db.quarantined-$(date +%Y%m%d)$suffix
   done
   ```

3. **Remove empty vestiges** (only after confirming the file is 0 bytes):

   ```bash
   ls -l ~/code/rh-workspace/.research-harness/pool.db   # confirm: 0 bytes
   rm ~/code/rh-workspace/.research-harness/pool.db
   ```

   The rh-workspace tree is a human-readable materialized view; it must never
   hold a database.

4. **Verify**:

   ```bash
   rh doctor            # state_trees line must read [OK]
   ```

## Recovering data from a quarantined DB

Open it read-only and re-ingest what matters into the canonical DB through
normal commands (`rh paper ingest`, `orchestrator_record_artifact`); do not
copy rows with raw SQL.

```bash
sqlite3 -readonly ~/.research-harness/pool.db.quarantined-YYYYMMDD \
  "SELECT id, name, status FROM topics"
```
