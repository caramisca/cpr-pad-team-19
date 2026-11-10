# Lab 4 Prometheus (Mihai)

Use `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring up -d prometheus`
once the team's Lab 4 broker and service images are integrated. The current root Compose remains
the published Lab 3 stack until the release PR pins reviewed Lab 4 commits/images; it does not
pretend that older 0.4.x images expose these metrics. Prometheus is local-only at http://localhost:9090.
Use `prometheus:9090` as Diana's Grafana datasource on the same Compose network.

DNS service discovery scrapes **each physical Applicant/Credential replica**, not one random
replica behind a shared service address. Other service owners must expose `/metrics` and add a
DNS job with their HTTP port. Broker's Compose service name must be `message-broker`.

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

Alert rules cover missing scrapes, more than 5 percent 5xx, and sustained event backlog. They are
visible in Prometheus; configuring an external Alertmanager notification is separate work.
No alerts are sent to teammates by this implementation.

Validate with `docker run --rm --entrypoint promtool -v "${PWD}/monitoring:/etc/prometheus:ro" prom/prometheus:v3.16.0 check config /etc/prometheus/prometheus.yml`.
