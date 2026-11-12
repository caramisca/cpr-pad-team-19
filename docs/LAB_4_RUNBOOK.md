# Laboratory 4 integration and release runbook

How the common stack runs with the Message Broker, how to check it, and in which order the Lab 4
images are released. Owner of this part: Daria (@DariaRateeva), with the broker, Service Discovery,
`player-service` and `server-moderation-session-service`. The other owners' Lab 4 work (queued
Gateway routing, durable queues and the dead letter channel, the broker's breakers and load-aware
routing, their services' gRPC adapters) is theirs; this runbook says where it plugs in.

## What `docker-compose.yml` runs in Lab 4

| Service | Image | Lab 4 role |
|---|---|---|
| `message-broker` | `drateeva/message-broker:0.5.0` | One instance, private: HTTP `8091` (`/health`, `/metrics`, `/topics`, `/dead-letters`), gRPC `9091` (`MessageBroker.Call`, `Publish`, `ListTopics`). Registers with the Service Discovery and finds subscribers and instances there. Durable topic queues and the dead letter channel in `/data/broker.sqlite3` on the named volume `broker-data` (`QUEUE_STORE_PATH`), so queued events survive a restart and `docker compose down` (not `down -v`) |
| `service-discovery` | `drateeva/service-discovery:0.5.0` | Registrations carry `topics`; `GET /topics`, `GET /topics/{topic}/subscribers` ([contract](SERVICE_DISCOVERY_CONTRACT.md)) |
| `player-service` | `drateeva/player-service:0.5.0` | `MESSAGING_ENABLED=true`: gRPC `ServiceEndpoint` on `9081`, topics `decision.evaluated`, `session.closed` |
| `server-moderation-session-service` | `drateeva/server-moderation-session-service:0.5.0` | `MESSAGING_ENABLED=true`: gRPC on `9082`, topic `decision.recorded`; publishes `session.started` / `session.closed` to `message-broker:9091` (`DMS_CLIENT_MODE=broker`); applicant and rules calls `http` by default, `broker` with `SESSION_APPLICANT_CLIENT_MODE=broker` / `SESSION_RULES_CLIENT_MODE=broker` (then the broker's circuit breakers guard them, not Session's) |

Nothing of the broker is published to the host, and no REST stand-in is on (`MOCK_EVENTS_ENABLED` is
never set in Compose). The Gateway still forwards client requests over HTTP; the queued routing of
client requests through the broker is the Gateway owner's switch (`BROKER_GRPC_URL`), and both of
Daria's services already answer `ServiceEndpoint.Call` the same way as HTTP (all endpoints but the
SSE stream).

## Start

```bash
cp .env.example .env            # then fill in the passwords and the API key
docker compose up -d
docker compose ps               # every service healthy after ~2 min (the Java replicas start last)
```

With monitoring: `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d`.
Applicant and credential over gRPC (Mihai's overlay, once University Record has its gRPC adapter):
add `-f docker-compose.lab4-mihai.yml` and set `SESSION_APPLICANT_CLIENT_MODE=broker` in `.env`, so
session's `next-applicant` reaches applicant-service through the broker too.

## Check the broker and the subscriptions

```bash
docker compose exec message-broker python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8091/health').read().decode())"
docker compose exec message-broker python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8091/topics').read().decode())"
```

Expected: `"status": "Healthy"`, and among the topics `decision.evaluated` and `session.closed` with
`player-service`, `decision.recorded` with `server-moderation-session-service` (plus the other
owners' topics once their services register them). The same list straight from the registry:
`docker compose exec service-discovery python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8089/topics').read().decode())"`.

Expected log lines (`docker compose logs <service> | grep ...`):

| Service | Line |
|---|---|
| `message-broker` | `message-broker 0.5.0 ready on port 8091 (...)`, then `Registered message-broker/<id> at http://<ip>:8091` |
| `player-service` | `gRPC ServiceEndpoint listening on port 9081: Message Broker deliveries of [decision.evaluated, session.closed] and client requests (Call)` |
| `server-moderation-session-service` | `gRPC ServiceEndpoint listening on port 9082: ... [decision.recorded] ...` and `session.started / session.closed are published to the Message Broker at message-broker:9091` |

## Smoke test through the Gateway

A shift closed in session reaches player through the broker and counts as a shift worked:

```bash
KEY=<one of the keys in GATEWAY_API_KEYS>
PLAYER=$(curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"discordId":"smoke-'$RANDOM'","displayName":"Smoke"}' http://localhost:8080/players | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
SESSION=$(curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"moderatorId":"'$PLAYER'"}' http://localhost:8080/sessions | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -X POST -H "Authorization: Bearer $KEY" http://localhost:8080/sessions/$SESSION/close
sleep 2; curl -s -H "Authorization: Bearer $KEY" http://localhost:8080/players/$PLAYER/stats   # "totalShifts": 1
```

Logs on the way: session `session.closed <eventId> published to the Message Broker (attempt 1):
queued for [player-service, ...]`, player `gRPC Deliver session.closed <messageId> from
server-moderation-session-service -> COMMITTED`. Then the Postman collections (README, "Running
`player-service` and `server-moderation-session-service`"); their stand-in requests are skipped
unless `standInUrl` names a local instance with `MOCK_EVENTS_ENABLED=true`.

## Log download (Grade 4)

Every replica of Player and Session serves `GET /internal/logs` (NDJSON, its last 1,000 requests);
the Gateway's `GET /logs` collects them with every other service's (Gateway `dev`, Andi):

```bash
curl -s -H "Authorization: Bearer $KEY" "http://localhost:8080/logs?service=player-service,server-moderation-session-service&limit=50"
curl -s -H "Authorization: Bearer $KEY" "http://localhost:8080/logs?requestId=<the X-Request-Id of one request>"
```

Every line has `service`, `instanceId` and `requestId`, so one request can be followed through every
replica it reached; the `X-Log-Sources` header says how many instances answered.

## Release checks

```bash
python3 scripts/check_lab4_release.py                      # images pinned, broker private and wired (CI on every PR)
python3 scripts/check_lab4_release.py --require-published  # also: public, amd64 + arm64, latest = pinned (PRs to main)
python3 scripts/check_lab4_monitoring.py --scope team      # Prometheus sees the replicas of every service
```

`check_lab4_release.py` builds on `check_lab3_release.py` (all application images pinned, nothing
built locally, private ports) and adds the broker image, its `/data` volume and the Lab 4 settings of
Player and Session. Keep the image list in `check_lab3_release.py` and the broker image in
`check_lab4_release.py` in sync with Compose.

## Release order

1. Feature PRs into each repository's `dev` (done for Daria's repositories: see their PRs).
2. Release PRs `dev` → `main` (merge commit, reviewed where the repository requires it) for
   `service-discovery`, `player-service`, `server-moderation-session-service`; each `main` CI run
   publishes `0.5.0` and `latest` for both architectures. Then the annotated tags `v0.5.0`.
3. `message-broker` `dev` → `main` once the teammates' broker work for Lab 4 is merged into `dev`
   (durable queues and dead letter channel, breakers, rerouting, load-aware routing); `main` CI
   publishes `drateeva/message-broker:0.5.0`.
4. CPR: submodule pointers to the release commits, `check_lab4_release.py --require-published`
   green, then the CPR release PR `dev` → `main`.

A later fix in one service is a patch release (`0.5.1`), changed in its Compose image, its expected
version in the check scripts and its submodule pointer together.

## Not covered yet (other owners)

- Gateway routing of client requests through the broker's queues, and its routes to `/internal/*`
  removed in a release (Gateway `dev`; the published `0.4.1` still forwards them, the services
  answer `404 ROUTE_NOT_FOUND` with the stand-ins off).
- Rerouting after a trip and load-aware routing in the broker (Diana). Durable queues, the dead
  letter channel and the breakers are in (broker #9, Andi).
- The broker's `MessageBroker.Call` accepts only `GET`, `POST`, `PUT`, `PATCH` and `DELETE`
  (`INVALID_ARGUMENT` otherwise), so a `HEAD` or `OPTIONS` routed through the broker never reaches a
  service; Player and Session answer both on their own `ServiceEndpoint.Call` as over HTTP.
- `discord-dms-service` `0.5.0` subscribes to `session.started` / `session.closed` and moderation
  publishes through the broker once Andi's pins (CPR #284) and `docker-compose.lab4-andi.yml` are
  applied. `server-rules-service` serves its gRPC `ServiceEndpoint` on its `dev` (not released yet):
  set `SESSION_RULES_CLIENT_MODE=broker` once its image does.
