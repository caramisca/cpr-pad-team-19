# server-moderation-session-service — DB scripts

PostgreSQL schema of `server-moderation-session-service`, managed by Flyway and applied
automatically on service startup (source of truth:
`services/server-moderation-session-service/src/main/resources/db/migration/`). Copied here for
visibility/testing per the CPR's Lab 1 requirement — edit the original in the service repo, not
this copy.

- `V1__init_schema.sql` — creates `sessions`, `session_junior_moderators` (the junior-moderator
  roster element collection), `session_queue_entry`, `session_summary`, and `processed_events`,
  with the foreign keys and indexes described in the CPR's Communication Contract.

There is no seed script: sessions are opened through `POST /sessions` and their queue/summary
populate as the shift runs, not from static demo data.
