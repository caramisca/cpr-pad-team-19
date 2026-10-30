# server-moderation-session-service — DB scripts

PostgreSQL schema of `server-moderation-session-service`, managed by Flyway and applied
automatically on service startup (source of truth:
`services/server-moderation-session-service/src/main/resources/db/migration/`). Copied here for
visibility/testing per the CPR's Lab 1 requirement — edit the original in the service repo, not
this copy.

- `V1__init_schema.sql` — creates `sessions`, `session_junior_moderators` (the junior-moderator
  roster element collection), `session_queue_entry`, `session_summary`, and `processed_events`,
  with the foreign keys and indexes described in the CPR's Communication Contract.
- `V2__queue_constraints_for_several_instances.sql` (Lab 3, `0.4.0`) — makes the queue safe with
  several instances on the same database: removes orphan queue entries, adds the foreign key from
  `session_queue_entry` to `sessions`, renumbers duplicate queue positions, adds the unique
  constraint `uq_session_queue_entry_position (session_id, queue_position)` and drops the index it
  makes redundant.

There is no seed script: sessions are opened through `POST /sessions` and their queue/summary
populate as the shift runs, not from static demo data.
