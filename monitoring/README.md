# Lab 5 monitoring

The root Compose uses the published Lab 5 application images. Start the stack with the monitoring profile:

```powershell
docker compose -f docker-compose.yml -f docker-compose.lab4-mihai.yml -f docker-compose.lab4-andi.yml -f docker-compose.lab5-cache.yml -f docker-compose.monitoring.yml --profile monitoring up -d --wait
```

Create `.env` from `.env.example` and set local secrets, including `GATEWAY_CACHE_PASSWORD`.
Prometheus is local-only at http://localhost:9090. Grafana is at
http://localhost:3000/d/lab4-services and uses `prometheus:9090` as its provisioned datasource.

On 26 November CPR commit `152ec94` served the 42-panel dashboard and all 20 Prometheus targets
reported UP in an isolated run. The dashboard includes all eight domain services. The Gateway
and Service Discovery jobs use Blackbox Exporter to check HTTP health. Rules and Record publish
separate `grpc_server_*` metrics alongside HTTP metrics.

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

A failed scrape is reported as DOWN. An absent DNS name can produce no targets at all, so also
check that the expected replicas appear. The Gateway and Service Discovery health jobs report
`probe_success`.

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
These services do not currently publish histogram buckets. The integrated Applicant/Credential panels use these counters and distinguish physical replicas.
Do not label a mean as P95 or assume an HTTP-only panel covers gRPC traffic.

Alert rules cover missing scrapes, more than 5 percent 5xx, and sustained event backlog. They are
visible in Prometheus; configuring an external Alertmanager notification is separate work.
No alerts are sent to teammates by this implementation.

Validate with `docker run --rm --entrypoint promtool -v "${PWD}/monitoring:/etc/prometheus:ro" prom/prometheus:v3.16.0 check config /etc/prometheus/prometheus.yml`.
