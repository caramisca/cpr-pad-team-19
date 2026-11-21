# Laboratory 5: two-phase commit for closing a shift

Lab 5, Grade 8: "for functionality that requires changes in 2 or more databases implement 2 Phase
Commits". Owner: Daria (@DariaRateeva). Closing a shift changes `session-postgres` (the shift) and
`player-postgres` (the shift credited to every moderator); with the two-phase commit both change or
neither does. The contract (API, answers, timeouts): [`contracts/two-phase.md`](../contracts/two-phase.md).

## What runs

| Piece | Where | Role |
|---|---|---|
| Coordinator | `message-broker` (`app/two_phase.py`), HTTP `POST /two-phase/transactions` on 8091 | Asks both participants to prepare, logs the decision in its SQLite file (`broker-data` volume), sends commit or abort until both acknowledged; recovers after a restart |
| Initiator | `server-moderation-session-service`, `POST /sessions/{id}/close` (`SHIFT_CLOSE_MODE=two-phase`) | Picks the transaction ID and `closedAt`, asks the coordinator, answers the client from the decision |
| Participants | both services, `POST /internal/two-phase/{id}/prepare\|commit\|abort` over gRPC `ServiceEndpoint.Call` | `PREPARE TRANSACTION` / `COMMIT PREPARED` / `ROLLBACK PREPARED` on their own database; a sweeper finishes what the coordinator left |
| Prepared transactions | `player-postgres`, `session-postgres` (Patroni) | `max_prepared_transactions: 20` (`docker/postgres-ha/patroni.yml`, mounted into every member) |

Compose turns it on: `SHIFT_CLOSE_MODE: ${SESSION_SHIFT_CLOSE_MODE:-two-phase}` and
`TWO_PHASE_PARTICIPANT_ENABLED: "true"` on both services, `TWO_PHASE_COORDINATOR_URL:
http://message-broker:8091`. `SESSION_SHIFT_CLOSE_MODE=event` in `.env` goes back to the Lab 4 way
(local close + `session.closed`).

## Why it is safe

- **Atomic:** the shift closes only if both participants prepared. A NO (`player-service`: someone in
  the shift isn't a registered player) or no answer in 3 s aborts both; the client gets
  `409 SHIFT_CLOSE_ABORTED` and nothing changed anywhere.
- **Durable decision:** the commit point is the decision row in the broker's SQLite file
  (`synchronous=FULL`). A broker restarted after that finishes the commit from its log.
- **Durable prepare:** `PREPARE TRANSACTION` writes the change to the WAL and waits for the
  synchronous standby (Grade 5), so it survives a crash of the service, of the database's primary
  (the promoted standby has it) and of the coordinator.
- **Counted once:** player-service records the transaction ID in `processed_events` in the same
  transaction; `session.closed`, published after the commit with that ID as `eventId`, is skipped.
- **Presumed abort, sweepers:** a transaction the coordinator doesn't know (log lost) or left
  `PREPARING` is aborted; each participant asks the coordinator about anything still prepared after
  30 s, so no row stays locked by a forgotten transaction.

## Start

**New clusters** (first start, or after `docker compose down -v`) read `max_prepared_transactions`
from the mounted `patroni.yml`. Check: `docker compose exec player-postgres-1 sh -c
'PGPASSWORD="$PATRONI_SUPERUSER_PASSWORD" psql -h player-postgres -U postgres -Atc "SHOW max_prepared_transactions"'`
→ `20`.

**Existing clusters** (volumes created before this change keep their settings in etcd): change it
once per cluster, wait a few seconds until `patronictl list` shows `Pending restart`, then restart
the members (standbys first, then the primary; a few seconds of `503 DATABASE_UNAVAILABLE`):

```bash
docker compose exec player-postgres-1 patronictl -c /etc/patroni/patroni.yml edit-config --set postgresql.parameters.max_prepared_transactions=20 --force
docker compose exec player-postgres-1 patronictl -c /etc/patroni/patroni.yml restart player-postgres --pending --force
```

The same with `session-postgres-1` / `session-postgres`. Without it every prepare fails (the
services log `max_prepared_transactions is 0` at startup) and every close answers
`409 SHIFT_CLOSE_ABORTED`.

## Check

**Automatic** (`scripts/check_two_phase_commit.py`, standard library only, no `.env` read; it
creates its own players and shifts). The three crash scenarios kill something between the decision
and phase 2, so start the broker with a demo delay first:

```bash
echo BROKER_TWO_PHASE_PHASE_TWO_DELAY_SECONDS=3 >> .env && docker compose up -d message-broker
python3 scripts/check_two_phase_commit.py --evidence docs/evidence/lab5-two-phase-commit.json
```

Remove the line from `.env` and run `docker compose up -d message-broker` again afterwards.
`--scenario commit|no-vote|participant-crash|coordinator-crash|database-failover` runs one.

**Manual demo** (through the Gateway, with the API key): register a moderator, open a shift, close
it → `200`; `GET /players/{id}/stats` → `totalShifts` + 1. Open a shift whose junior moderator is a
random UUID and close it → `409 SHIFT_CLOSE_ABORTED` naming the unknown player; the shift is still
`OPEN`. The coordinator's view: `docker compose exec message-broker python -c "import
urllib.request; print(urllib.request.urlopen('http://localhost:8091/two-phase/transactions?limit=5').read().decode())"`.

## Measured (local Docker, 2026-11-22)

The three branch images, 2 replicas of each service, both clusters, phase-2 delay 3 s. Evidence:
[`evidence/lab5-two-phase-commit-2026-11-22.json`](evidence/lab5-two-phase-commit-2026-11-22.json).

| Scenario | What happened | Result |
|---|---|---|
| Commit | close → `200` in 3.6 s (3 s of it the demo delay) | both databases changed; shift counted once after `session.closed`; nothing left prepared |
| NO vote | junior moderator not a registered player | `409 SHIFT_CLOSE_ABORTED`; shift `OPEN`; moderator not credited; nothing prepared |
| Participant crash | every `player-service` replica killed after the decision | close `200` (session committed); player's part still prepared; committed by the broker 26 s after the restart, credited once |
| Coordinator crash | `message-broker` killed after writing the decision | close `503 DEPENDENCY_UNAVAILABLE`; both parts prepared meanwhile; committed from the log 8 s after the restart |
| Database failover | primary of `player-postgres` killed while prepared | close `200`; the promoted standby had the prepared transaction; committed there 36 s after the kill; old primary rejoined |

Also checked by hand the same day: a transaction prepared at `player-service` that the coordinator
never heard of was rolled back by the sweeper after 34 s (presumed abort), and `edit-config` +
`restart --pending` (above) changed `max_prepared_transactions` on a running cluster.

## Notes

- The tests of both services run the participant on a real PostgreSQL (Testcontainers; skipped
  without Docker), since H2 has no `PREPARE TRANSACTION`.
- A prepared transaction keeps its locks: a `decision.recorded` or `decision.evaluated` for the same
  shift or players waits for the decision (broker deliveries answer `RETRY` after the task timeout).
- Losing the broker's log (`docker compose down -v`) while a transaction is decided but not
  acknowledged loses its outcome: the sweepers then roll it back (presumed abort).
