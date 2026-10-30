# Service Discovery communication contract

This is the common contract for the Python Service Discovery and all callers. It describes the
integrated SD API, including the status and notification features on its `dev` branch. Availability
in a release requires a published image and a CPR submodule pointer to that release.

## Boundary and addressing

SD owns only its in-memory instance registry and monitoring. Domain services keep their own
databases. Clients reach domain HTTP APIs through Gateway; they do not use SD as a business proxy.
SD is one process at `http://service-discovery:8089` on the private Compose network. Neither SD
8089 nor Gateway's internal 8090 is published to the host. These control-plane calls need no API
key; public Gateway 8080 still requires its configured API key.

Each physical replica registers a unique `instanceId` and its own reachable container URL. A
shared service DNS name is not a physical-instance address: Gateway must be able to select,
monitor and remove one replica independently. The default instance ID is the container hostname.

## Register on startup: `POST /instances`

Register after the HTTP listener starts. Content type is `application/json`:

```json
{
  "serviceName": "applicant-service",
  "instanceId": "applicant-1",
  "url": "http://172.18.0.7:8083",
  "healthUrl": "http://172.18.0.7:8083/health"
}
```

The address is illustrative, discovered at runtime, and must not be hard-coded in Compose.

| Field | Validation |
|---|---|
| `serviceName` | Required; lowercase letters, digits and `-`, maximum 64 characters, no leading/trailing `-` |
| `instanceId` | Required; letters, digits, `.`, `_`, `:`, `-`, maximum 64 characters; unique within the service |
| `url` | Required; absolute HTTP(S) URL with a host, no query/fragment, maximum 2048 characters; trailing slash removed |
| `healthUrl` | Optional HTTP(S) URL; defaults to `url` + `/health` |

A new registration returns `201 Created`; re-registering the same ID returns `200 OK` and updates
its address while retaining registry order. Response:

```json
{
  "serviceName": "applicant-service",
  "instanceId": "applicant-1",
  "url": "http://172.18.0.7:8083",
  "healthUrl": "http://172.18.0.7:8083/health",
  "registeredAt": "2026-10-29T09:00:00Z",
  "lastHeartbeat": "2026-10-29T09:00:00Z",
  "ttlSeconds": 30.0,
  "heartbeatIntervalSeconds": 10.0
}
```

Invalid JSON or fields return `400 VALIDATION_ERROR`. Callers retry unavailable SD with bounded
backoff and jitter while continuing to serve business requests.

## Heartbeat, shutdown and lookup

| Operation | Request | Success | Missing instance |
|---|---|---|---|
| Heartbeat | `PUT /instances/{serviceName}/{instanceId}/heartbeat`, no body | `204` | `404 INSTANCE_NOT_FOUND`; register again |
| Deregister | `DELETE /instances/{serviceName}/{instanceId}`, no body | `204` | `404 INSTANCE_NOT_FOUND`; already absent |
| Service lookup | `GET /services/{serviceName}/instances` | `200`, `{"serviceName":"applicant-service","instances":[...]}` | `200` with an empty list |
| Full lookup | `GET /instances` | `200`, `{"instances":[...]}` | `200` with an empty list |

Each lookup entry has `serviceName`, `instanceId`, `url`, `healthUrl`, `registeredAt` and
`lastHeartbeat`, using the registration response's types. Timestamps are UTC ISO 8601 strings.
Entries retain registration order. Heartbeat cadence comes from the registration response, by
default TTL / 3. An instance expires after its last heartbeat is older than the TTL; lookups and
the background sweep remove expired entries. Graceful shutdown attempts a bounded best-effort
DELETE. A restarted SD has an empty registry: heartbeat 404 triggers registration again.

Other errors share `{"error":"CODE","message":"description"}`: unknown route `404
ROUTE_NOT_FOUND`, wrong method `405 METHOD_NOT_ALLOWED`, unexpected failure `500 INTERNAL_ERROR`.
SD also returns `503 TOO_MANY_REQUESTS` at its inbound concurrency limit and `504 REQUEST_TIMEOUT`
on its inbound task deadline. Its `/health` bypasses both limits.

## Status: `GET /health`

Each monitored service exposes status/load at its registered `healthUrl`:

```json
{
  "status": "Healthy",
  "service": "service-discovery",
  "version": "0.4.0",
  "instanceId": "sd-1",
  "checks": {},
  "activeThreads": 0,
  "maxThreads": 200,
  "load": "NORMAL"
}
```

`activeThreads` and `maxThreads` are integers describing active work and capacity, rather than OS
thread counts. `NORMAL` is at most 50%, `HIGH` is above 50% through 80%, `CRITICAL` is above 80%.
Storage checks determine `Healthy`/200 or `Unhealthy`/503 independently of load. SD has no database
and its own health does not fail because a monitored service is down. Status probes do not occupy
business concurrency slots. Requests propagate `X-Request-Id`; logs identify the physical instance.

A service may add fields of its own after `maxThreads`. SD reads only the HTTP status, `load` and,
for the alert text, `activeThreads`/`maxThreads`. `server-moderation-session-service` adds its SSE
streams, `openStreams` (open on this instance) and `maxStreams` (`SSE_MAX_CONNECTIONS`), and its
`load` is the worse of the task load and the stream load: a replica full of streams reports
`CRITICAL` (and is alerted) even while its `activeThreads` is low.

## Monitoring and developer notifications

SD polls registered health endpoints at `POLL_INTERVAL_SECONDS` (default 10 seconds between
cycles), with at most four instances in flight. Critical-load reports are logged and passed to
the notifier even on a 503 health response. The notifier sends to whichever channels are set:

| Root Compose `.env` key | Container key |
|---|---|
| `DISCOVERY_ALERT_DISCORD_WEBHOOK_URL` | `ALERT_DISCORD_WEBHOOK_URL` |
| `DISCOVERY_ALERT_TELEGRAM_BOT_TOKEN` | `ALERT_TELEGRAM_BOT_TOKEN` |
| `DISCOVERY_ALERT_TELEGRAM_CHAT_ID` | `ALERT_TELEGRAM_CHAT_ID` |
| `DISCOVERY_ALERT_COOLDOWN_SECONDS` | `ALERT_COOLDOWN_SECONDS` |

Telegram needs both token and chat ID. Without either channel configured, alerts remain log-only.
Credentials stay in ignored local environments or CI secrets. Notifications are queued, deduplicated
by cooldown and retried without making registration or polling wait for the external channel.
Receiving a fixture alert in a test does not prove delivery to a developer's real channel.

The monitoring fix integrated through SD #8 and released in SD 0.4.0 confirms a failed health GET with at most two
additional probes within the same cycle. Each whole GET is bounded to `min(3 seconds, window / 4)`;
the circuit still requires three actual failures within `REQUEST_TIMEOUT_SECONDS * 3.5`. A healthy
response stops confirmation; an open monitor suppresses further probes until its recovery window.
Monitor circuits protect health calls; they do not remove business routing entries.

## Business circuit breaker and physical removal

Gateway's circuit belongs to one physical downstream address, across its endpoint paths. The third
transport/timeout/5xx failure inside the task-timeout-times-3.5 window opens it. Gateway patch
0.4.1 excludes an upstream 503 busy/dependency reply from this count, so a working caller is not
removed merely because its dependency is unavailable; other 5xx, transport errors and timeouts
still count. This does not change SD's separate classification of failed health probes. G10 immediately
excludes that address from round-robin and asynchronously sends SD DELETE for its instance ID.
Other healthy replicas remain routable. Static service DNS must not bypass quarantine.

An instance that is alive re-registers after heartbeat 404. Gateway retains its local quarantine
until the recovery period ends, then permits one trial request; success closes the circuit and
failure removes the instance again. If SD DELETE fails, local exclusion still applies. With no
eligible discovered instances Gateway returns `503 NO_AVAILABLE_INSTANCES`.

Applicant and Credential also protect their own outbound business dependencies. They call Gateway
8090 and do not know the physical replica selected downstream: they must not deregister Gateway
or a shared service address. The physical-removal responsibility remains with Gateway.

`server-moderation-session-service` also keeps one circuit per dependency (`applicant-service`,
`server-rules-service`, `discord-dms-service`) on its calls through Gateway 8090, and never
deregisters Gateway or a shared address either. When one of its circuits opens, it asks SD for that
dependency's instances (`GET /services/{serviceName}/instances`), sends each one's `healthUrl` a
health check, and deregisters only the physical instances that fail it (no `2xx`, or a `status`
other than `Healthy`); instances that pass stay registered. It complements Gateway's removal, for an
instance that fails its health check while Gateway has not yet tripped its circuit.
