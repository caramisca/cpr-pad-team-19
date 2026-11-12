# Lab 4 message contract (v1)

Owner: Mihai / @caramisca. Canonical schema: [`contracts/messaging.proto`](../contracts/messaging.proto).
Copies in Broker, Applicant and Credential must be byte-identical. Domain JSON fields already
documented in CPR stay unchanged; protobuf `bytes` carries their UTF-8 JSON serialization.

## Network and operations

| Component | HTTP health/metrics/logs | Private gRPC |
|---|---|---|
| Message Broker | 8091 | 9091 |
| Applicant | 8083 | 9083 |
| Credential | 8084 | 9084 |
| Other services (adapter owned by each author) | existing HTTP port | HTTP port + 1000 |

All gRPC ports stay private on the Compose network. No Gateway ingress to them. Development
uses cleartext HTTP/2 on that private network; the .NET listener explicitly requires HTTP/2.
Discovery continues to register the physical instance's HTTP URL and health URL. Broker derives
its gRPC address from **the same host and HTTP port + 1000**, never a shared service DNS alias.
If overriding a service port, override `Messaging__HttpPort`, `Messaging__GrpcPort` and its advertised
URL consistently. Port 8090 on the old Gateway is not used by the new gRPC dependency mode.

`MessageBroker.Call(ServiceRequest)` invokes the target's `ServiceEndpoint.Call` and returns
`ServiceReply {status, body, headers}`. Method/path and existing business JSON schemas are retained,
so Java and .NET teams can adapt their existing handlers. No REST business hop is hidden inside
Applicant/Credential: their gRPC server invokes the same domain handlers directly. UUID message ID,
source service, logical target, method, absolute path and request ID identify the operation.
Channels are reused per physical instance, preserving HTTP/2 connections across requests.
The caller's deadline is bounded to five seconds at broker forwarding; cancellation propagates.
`X-Request-Id` is also gRPC metadata for correlated HTTP/2 access logs.

The integrated broker `request_dispatch` still invokes the transport directly. Diana replaces that
hook with subscriber request/reply queues; topic queues do not implement that request/reply layer.
Instance selection already uses Andi's per-instance circuit breaker and Diana's selector. Open
circuits are excluded; if every instance is open, the call fails fast with `CIRCUIT_OPEN`.
The defaults are three failures within 17.5 seconds, a 17.5-second open period and one permitted
half-open trial. A transport failure or `Deliver` RETRY counts against the instance; application
503, 4xx and REJECTED do not. The integrated `Call` makes one selected downstream attempt;
retrying that same failed call on another instance and feeding real load into the selector remain
separate integration work. Excluding an already-open circuit is not proof of same-call retry.
Mutating requests must not be replayed automatically after an ambiguous timeout without domain
idempotency. Transport failure is gRPC UNAVAILABLE; validation failure is INVALID_ARGUMENT.
Application errors remain `ServiceReply.status` with the existing JSON error shape.

HTTP adapters must retain the query string inside `ServiceRequest.path`, for example
`/applicants?sessionId=<uuid>` and `/credentials?applicantId=<uuid>`. A path without its
query silently removes business filters. `ServiceReply.headers` includes `Content-Type`
for JSON, `Location` for created resources, `X-Request-Id` and `X-Instance-Id`; the Gateway
must restore these headers along with status and body. Applicant/Credential contract tests
compare the gRPC and REST responses for filtered lists and JSON 400/404 errors.

## Event envelope

HTTP `POST /events` and gRPC `MessageBroker.Publish(Event)` use the same topic bus. Example HTTP:

```json
{
  "messageId": "7d584457-28ee-42f6-9a34-1e3cdeab3490",
  "source": "server-moderation-session-service",
  "topic": "session.closed",
  "occurredAt": "2026-11-09T20:00:00Z",
  "schemaVersion": 1,
  "requestId": "trace-123",
  "payload": {"sessionId": "5e55a0e0-0000-4000-8000-000000000001"}
}
```

IDs are immutable on retries. `payload` is an object, not a JSON string. The HTTP version uses
`X-Request-Id`; protobuf uses `request_id`. Source/topic are lower-case safe identifiers; topic
names use dots, hyphens or underscores. Body limit: 1 MiB. `occurredAt` includes timezone.
`202 {messageId, queuedServices}` / `PublishReply` means every subscriber copy was enqueued,
**not that consumers committed**. No live subscribers is a valid empty result; no future replay
is promised for services that register after publication. Publishers never provide recipients.

Broker asks SD `GET /topics/{topic}/subscribers`, snapshots the logical service names, and enqueues
one independent copy in `topics/<topic>/<service>`. Multiple replicas share that service copy.
Only instances currently subscribed to that topic can receive it. `GET /topics` and gRPC
`ListTopics` reflect live SD subscriptions, including expiry/removal, rather than a static catalog.

| Delivery outcome | Meaning | Broker behavior |
|---|---|---|
| `COMMITTED` | Domain mutation and necessary outbox writes completed; duplicates already committed count too | Acknowledge that service copy |
| `RETRY` | Temporary storage/dependency failure | Retain; retry after lease |
| `REJECTED` | Invalid envelope/payload or unsupported topic | Store the copy in the dead letter channel, then acknowledge only after successful storage |

If the RPC deadline or request cancellation occurs before storage reports its failure, the
caller can receive a transport error instead of a `DeliveryReply`. This never authorizes ACK:
the broker keeps that copy pending. Explicit RETRY requires the storage operation to fail within
the remaining RPC/request budget; align storage timeouts with that budget when integrating.

## Integrated durable queues and dead letter channel

Broker #9 implements SQLite topic queues and a dead letter channel. Set `QUEUE_STORE_PATH` to
enable them; the Docker image defaults to `/data/broker.sqlite3`. Mount a persistent volume at
`/data` and keep the same file when restarting or replacing the broker. The database uses WAL and
`synchronous=FULL`. All subscriber copies are committed before publication succeeds, or none are
accepted. A pending copy is removed only after COMMITTED or successful dead-letter storage.

If `QUEUE_STORE_PATH` is empty, the broker uses `MemoryTopicStore` and `MemoryDeadLetters` for
development. They do **not** survive restart. Service outboxes cannot recover an event that the
broker accepted into memory and then lost after the publisher removed its outbox entry.

| Setting | Default | Meaning |
|---|---|---|
| `QUEUE_STORE_PATH` | empty in native configuration; `/data/broker.sqlite3` in the image | SQLite file for queues and dead letters |
| `QUEUE_CAPACITY` | 10000 | Maximum pending copies across topic queues; over-capacity fan-out is refused atomically |
| `QUEUE_LEASE_SECONDS` | 10 | FIFO head lease; must exceed the three-second delivery deadline |
| `MAX_DELIVERY_ATTEMPTS` | 0 | Retry until COMMITTED/REJECTED; a positive value also dead-letters repeatedly failing copies |

SQLite stores wall-clock lease deadlines, so an unacknowledged copy becomes eligible again after
its lease expires even across broker restart. FIFO remains per `topics/<topic>/<service>`, not a
global order across topics. A missing subscriber instance or an open circuit is not a delivery
attempt. The optional attempt counter is held in the running broker, so a positive retry limit is
not a lifetime attempt budget persisted across restarts.

The internal Python hook is now:

```python
topic_bus.on_rejected(queue, event, reason, attempts) -> bool
```

The broker wires it to `dead_letters.add`. Return True only when that service copy is stored
(including an already-stored copy); False or a storage exception keeps the original copy pending.
This ordering also handles a crash after DLC insertion but before queue acknowledgement: replay
does not create another dead letter for the same queue/message ID. The durable store and DLC must
both be enabled for this guarantee; custom injected stores must supply a matching DLC explicitly.
`GrpcDelivery.deliver` passes both the outcome and the consumer's reason to the topic bus.
These Python integration changes do **not** change `messaging.proto` or the protobuf outcomes.

### Dead-letter inspection and health

Private HTTP `GET /dead-letters?topic=session.closed&service=applicant-service&limit=20` returns
`{total, deadLetters}` with the newest matching entries first. Filters are optional; `limit`
defaults to 100 and must be 1..1000. Each entry contains `messageId`, `topic`, `service`, `queue`,
`source`, `requestId`, `reason`, `attempts`, `deadLetteredAt`, its numeric `id`, and the full `event`.
`total` counts all matching entries before the limit. Invalid filters return 400 VALIDATION_ERROR.
This is an internal diagnostic API: unlike the sanitized request logs, a dead letter includes
its business payload. An envelope rejected at publication with 400 never entered the queues and
does not by itself demonstrate the dead letter channel.

With SQLite active, `/health` includes `checks.queues`; unreadable storage makes health unhealthy
and queue operations return 503 QUEUE_UNAVAILABLE. A file that cannot be opened prevents startup.
Broker reliability can be repeated with `python scripts/probe_reliability.py` from its repository:
the probe kills/restarts a real broker against one file, with explicitly labelled SD/consumer
fixtures. That scoped proof is separate from acceptance with all real team services.

## Topic catalog

The existing domain payload fields stay as documented in the CPR README. This table records
intended subscriptions; adapters in teammates' services are their owners' work.

| Topic | Producer | Consumers |
|---|---|---|
| `decision.recorded` | Moderation | Session |
| `decision.evaluated`, `decision.amended`, `decision.voided` | Moderation | Player |
| `verdict.issued` | Moderation | DMS |
| `session.started` | Session | DMS |
| `session.closed` | Session | DMS; Applicant (implemented) |
| `ruleset.updated` | Rules | DMS |
| `applicant.generated` | Applicant (implemented) | Optional observers; none required |
| `applicant.deleted` | Applicant (implemented) | Credential (implemented) |
| `credential.issued`, `credential.revoked` | Credential (implemented) | Optional observers; none required |

New payloads: `applicant.generated {applicantId,sessionId,credentialId}`;
`applicant.deleted {applicantId,sessionId}`; `credential.issued`/`credential.revoked
{credentialId,applicantId}`. The last two cleanup topics concern explicit lifecycle deletion;
normal TTL expiry remains the existing independent Redis retention policy.

Applicant registers `topics: ["session.closed"]`; Credential registers `["applicant.deleted"]`.
Session close deletes that session's applicants. Each Applicant deletion atomically emits
`applicant.deleted`; Credential deletes that applicant's bundles and emits `credential.revoked`.
Shared Redis inbox markers make redelivery to another replica safe. Cleanup itself is idempotent;
if a process dies before writing its inbox marker, replay safely finishes missing deletions.
Redis outbox entries are created in the same transaction as domain creates/deletes and remain
until Publish succeeds. Local InMemory mode is for development and has no restart guarantee.

## Logs and metrics

Applicant/Credential expose private `GET /internal/logs` as `application/x-ndjson`, last 1,000
business requests per instance, chronological. Fields: timestamp, service, instanceId, requestId,
method, status, durationMs. No headers, bodies, query values or secrets. This is the collection
interface for Andi's Gateway download endpoint; console logs also remain available via Docker.
The ring is volatile, so it is a live diagnostic window, not a permanent audit archive.

`GET /metrics` is Prometheus text format. Applicant/Credential expose `service_requests_total`,
`service_errors_total` (5xx), `service_request_duration_seconds_sum`, and `service_active_requests`.
Health, metrics and log polling do not count as business work. Broker exposes
`broker_events_accepted_total`, `broker_event_deliveries_total{outcome}`, `broker_active_requests`,
`broker_pending_event_copies`. Reliability adds `broker_open_circuits`,
`broker_circuit_transitions_total{state}` and `broker_dead_letter_messages`. Storage-backed gauges
report NaN if storage cannot be read rather than making the entire metrics endpoint fail.
Labels intentionally exclude message/request/entity IDs.
The Prometheus job labels supply the service and physical instance address.

Protocol references: [gRPC Python](https://grpc.io/docs/languages/python/basics/),
[ASP.NET Core HTTP/2 requirements](https://learn.microsoft.com/aspnet/core/grpc/aspnetcore).
