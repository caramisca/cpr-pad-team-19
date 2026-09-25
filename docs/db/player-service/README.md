# player-service — DB scripts

PostgreSQL schema of `player-service`, managed by Flyway and applied automatically on service
startup (source of truth: `services/player-service/src/main/resources/db/migration/`). Copied
here for visibility/testing per the CPR's Lab 1 requirement — edit the original in the service
repo, not this copy.

- `V1__init_schema.sql` — creates `players`, `player_stats`, and `processed_events` with the
  foreign keys and unique constraints described in the CPR's Communication Contract.

There is no seed script: players are created through `POST /players` and progress via the
`decision.evaluated` consumer, not from static demo data.
