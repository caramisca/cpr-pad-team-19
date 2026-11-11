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

The initial broker `request_dispatch` invokes the transport directly. Diana replaces that hook
with subscriber request/reply queues; the existing selector/breaker hooks are used for instance
selection. This contract does not claim her queued RPC routing or Andi's breaker is implemented.
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
| `REJECTED` | Invalid envelope/payload or unsupported topic | Retain for Andi's dead-letter handoff; acknowledge only after DLC persistence |

The supplied bounded memory store is a development implementation: 10,000 pending copies, FIFO
per topic/service, 10 s lease, atomic capacity check for fan-out. It does **not** survive broker
restart. Grade 9 reliability requires Andi to inject a durable `topic_store` into `Broker`, implement
`put_many` atomically, `queues`, leased `take`, `size`, `acknowledge`, and connect
`topic_bus.on_rejected(queue,event)` to a durable DLC. Until then, accepted events can be lost on
broker restart; a service outbox alone does not fix that gap. `REJECTED` intentionally blocks its
queue's FIFO head until the DLC handoff is installed.

## Topic catalog

The existing domain payload fields stay as documented in the CPR README. This table records
intended subscriptions; adapters in teammates' services are their owners' work.

| Topic | Producer | Consumers |
|---|---|---|
| `decision.recorded` | Moderation | Session (implemented) |
| `decision.evaluated` | Moderation | Player (implemented) |
| `decision.amended`, `decision.voided` | Moderation | Player (planned, not registered yet) |
| `verdict.issued` | Moderation | DMS |
| `session.started` | Session (implemented) | DMS |
| `session.closed` | Session (implemented) | DMS; Applicant (implemented); Player (implemented: counts `totalShifts`) |
| `ruleset.updated` | Rules | DMS |
| `applicant.generated` | Applicant (implemented) | Optional observers; none required |
| `applicant.deleted` | Applicant (implemented) | Credential (implemented) |
| `credential.issued`, `credential.revoked` | Credential (implemented) | Optional observers; none required |

New payloads: `applicant.generated {applicantId,sessionId,credentialId}`;
`applicant.deleted {applicantId,sessionId}`; `credential.issued`/`credential.revoked
{credentialId,applicantId}`. The last two cleanup topics concern explicit lifecycle deletion;
normal TTL expiry remains the existing independent Redis retention policy.

Applicant registers `topics: ["session.closed"]`; Credential registers `["applicant.deleted"]`;
Player registers `["decision.evaluated", "session.closed"]`; Session registers `["decision.recorded"]`.
Since session `0.5.0`, `session.closed` also carries `moderatorId` and `juniorModeratorIds` (README,
"Endpoint Contracts"), so Player credits the shift without having kept `session.started`.
Player and Session serve `ServiceEndpoint.Call` for every client endpoint except Session's SSE stream
`GET /sessions/{id}/events`, which stays direct HTTP through the Gateway (through `Call` it is
answered `406 NOT_ACCEPTABLE`).
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
`broker_pending_event_copies`. Labels intentionally exclude message/request/entity IDs.
The Prometheus job labels supply the service and physical instance address.

Protocol references: [gRPC Python](https://grpc.io/docs/languages/python/basics/),
[ASP.NET Core HTTP/2 requirements](https://learn.microsoft.com/aspnet/core/grpc/aspnetcore).
