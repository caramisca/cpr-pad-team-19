# Lab 4 Prometheus (Mihai)

Use `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring up -d prometheus`
once the team's Lab 4 broker and service images are integrated. The current root Compose remains
the published Lab 3 stack until the release PR pins reviewed Lab 4 commits/images; it does not
pretend that older 0.4.x images expose these metrics. Prometheus is local-only at http://localhost:9090.
Use `prometheus:9090` as Diana's Grafana datasource on the same Compose network.

DNS service discovery scrapes **each physical replica**, not one random replica behind a shared
service address. The configuration includes all eight domain services, the broker and Prometheus.
DMS discovery includes both `discord-dms-service` and `discord-dms-service-replica`, because the
WebSocket host port uses a separate Compose service. Broker's Compose name must be `message-broker`.

| Owner | Service(s) | Private metrics endpoint expected by this config |
|---|---|---|
| Mihai | Applicant / Credential | `:8083/metrics` / `:8084/metrics` |
| Diana | Rules / Record | `:8085/actuator/prometheus` / `:8086/actuator/prometheus` |
| Daria | Player / Session | `:8081/actuator/prometheus` / `:8082/actuator/prometheus` |
| Andi | Moderation / DMS | `:8087/metrics` / `:8088/metrics` |
| Shared | Broker | `message-broker:8091/metrics` |

This defines the scrape integration expected from each owner's Lab 4 build; it does not assert
that private service implementations or published 0.4.x images provide those endpoints. Owners
must confirm these interfaces before the common release. Failed scrapes stay DOWN; an absent DNS
name can produce no targets at all and must also fail readiness. Gateway and SD have no metrics
contract in this overlay.

Run `python scripts/check_lab4_monitoring.py --scope team` against the final stack. It requires
two distinct UP targets per domain service plus broker/Prometheus, including jobs whose DNS
currently resolves no targets. Use `--scope owned` only for the explicitly scoped Mihai test
stack; its success does not mean the whole team is ready. `--evidence <file.json>` saves results.

Useful queries for Diana's dashboards:

```promql
sum by (job) (rate(service_requests_total[2m]))
sum by (job) (rate(service_errors_total[2m]))
sum by (job) (rate(service_request_duration_seconds_sum[2m])) / clamp_min(sum by (job) (rate(service_requests_total[2m])), 0.01)
service_active_requests
broker_pending_event_copies
sum by (outcome) (rate(broker_event_deliveries_total[2m]))
up
```

For Applicant/Credential panels, select `job=~"applicant-service|credential-service"` on the
`service_*` series above. The duration sum divided by request count is **mean latency**, not P95.
These services do not currently publish histogram buckets. Diana's Spring-only HTTP/P95 panels
do not automatically include the C# counters; add the corresponding panels in her dashboard PR.

Alert rules cover missing scrapes, more than 5 percent 5xx, and sustained event backlog. They are
visible in Prometheus; configuring an external Alertmanager notification is separate work.
No alerts are sent to teammates by this implementation.

Validate with `docker run --rm --entrypoint promtool -v "${PWD}/monitoring:/etc/prometheus:ro" prom/prometheus:v3.16.0 check config /etc/prometheus/prometheus.yml`.
