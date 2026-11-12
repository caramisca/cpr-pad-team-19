# Lab 4: Mihai integration verification, 12 November 2026

This delivery updates the shared contract to the integrated Broker #9 and verifies Mihai's
published Applicant/Credential 0.5.0 against the current Gateway and broker. It does not certify
the complete team stack. No protobuf schema, image pin or submodule pointer is changed here.

## Results and scope

| Check | Result | Scope boundary |
|---|---|---|
| Gateway -> broker -> Applicant -> broker -> Credential | Passed with two independently generated synthetic sessions | Real containers and shared Redis; no University Record fixture |
| Query filters and JSON headers | Passed through Gateway with distractor data, 201/400/404, Content-Type, Location, request/instance IDs | Uses the query-string fix from Gateway #25 |
| Topic cleanup | Passed; closing one test session removed its Applicant and Credential and preserved the other session | The probe publishes session.closed; it does not replace or certify Daria's real Session publisher |
| Duplicate delivery | Both physical Applicant replicas returned COMMITTED for the already-processed event | Shared Redis inbox; no exactly-once delivery claim |
| Invalid payload | Real Applicant REJECTED response reached the broker DLC with its reason | Valid envelope, invalid topic payload; not merely a publish-time 400 |
| Redis outage and broker restart | RETRY observed, an accepted cleanup copy recovered after broker kill/restart, earlier DLC entry retained | Explicit RETRY used a test-only 30-second service budget and a 20-second direct probe deadline; normal broker deadline stayed three seconds |
| Grafana request rate, 5xx, mean duration and active requests | All four new panel expressions returned finite series for both replicas of both services | Exact panel JSON from CPR #285; subsequently merged unchanged in meaning |
| University Record real adapter | Not verified: the legitimate issue request returned 503 | The expected public Record 0.5.0 image was unavailable at verification; no fixture is claimed as completion |

Evidence: [Gateway/business/topics](evidence/lab4-owned-gateway-2026-11-12.json),
[Grafana queries](evidence/lab4-owned-panels-2026-11-12.json),
[real-service recovery](evidence/lab4-owned-recovery-2026-11-12.json),
[source/configuration context](evidence/lab4-owned-context-2026-11-12.json).

With the default five-second request budget, the Redis backlog failure was observed after request
cancellation and the direct call returned gRPC UNKNOWN rather than an explicit RETRY. The broker
kept the message pending and it processed after recovery. The longer test budget separates storage
failure handling from deadline handling; it is not a change to published image defaults. Align the
normal storage/request/forwarding budgets in final integration if an explicit outcome is required
before deadline. Default timeout configuration was restored after testing.

The four new Grafana expressions were checked with actual traffic and finite results for each
physical replica. This change includes the instance in the request/error/mean-duration legends,
so the two replicas no longer share indistinguishable legend text. No metric expression changed.

## Repeating the owned Gateway check

Use a dedicated test stack with the current Gateway, broker, SD, Redis and two replicas of each
owned service. `scripts/lab4_owned_gateway_probe.py` runs inside the broker container, where
`app.generated` and the private gRPC addresses are available. Provide the local test key only
through `LAB4_TEST_API_KEY`; the script never includes it in its output.

```powershell
# Set LAB4_TEST_API_KEY locally to the key of the dedicated Gateway.
Get-Content -Raw scripts/lab4_owned_gateway_probe.py |
  docker compose exec -T -e LAB4_TEST_API_KEY message-broker python -
```

Use the same Compose files/project as your dedicated stack. The script defaults to
`http://gateway-owned-check:8080`, `http://message-broker:8091`, and
`http://service-discovery:8089`; pass `--gateway-url`, `--broker-url`, or `--discovery-url` after
`python -` when the service names differ. It creates unique sessions and publishes cleanup for
them in `finally`. The bounded generation loop tolerates 503 from currently unavailable registry
lookups; a successful synthetic issue does not demonstrate a legitimate registry lookup.
The output separates `passed` for these owned checks from `realUniversityRecordVerified`.

## Contract changes documented

- SQLite queues and DLC are integrated; the image defaults to `/data/broker.sqlite3` and still
  requires a persistent `/data` volume. Native empty QUEUE_STORE_PATH retains development memory mode.
- The Python hook is `on_rejected(queue, event, reason, attempts)`; persistence precedes ACK.
- `GrpcDelivery.deliver` supplies outcome and reason. The protobuf outcomes are unchanged.
- Documented DLC filters/response, health/storage failure semantics, capacity/leases and the
  optional retry-limit counter's process-local lifetime.
- The breaker exists. Request/reply queues, same-call rerouting and live load-cache feeding are
  separate integration work. Transport failure/deadline is not a successful acknowledgement.

## Team changes observed during verification

- CPR #285 (owned service panels) and #286 (Gateway BROKER_GRPC_URL configuration) merged into dev.
- Gateway #25 is integrated and preserves the query string. Gateway #26 changes only the workflow
  filename; its latest observed GitHub runs still report startup_failure, with no jobs started.
- CPR #284 merged while this verification was in progress; this branch includes the new
  Moderation/DMS 0.5.0 pins. The real Session publisher and common broker activation still need
  verification together: the old DMS internal event stand-in was removed in 0.5.0.
  Do not treat these owned probes as approval to release the complete stack.

Still required for full acceptance: real University Record over gRPC, real Session publication,
subscriber request/reply queues, all service adapters/releases and the common Compose deployment,
load-aware routing/HA and monitoring of the whole team.
