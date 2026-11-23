# Lab 5 · Gateway cache and Redis failover

## Gateway cache · G6 and G7

The Gateway cache branch is `feat/gateway/lab5-cache` in [`gateway-service`](https://github.com/diana7376/gateway-service/tree/feat/gateway/lab5-cache). Build that checkout, set `GATEWAY_CACHE_PASSWORD` in `.env` and start the cache overlay with the regular stack.

```bash
docker build -t pad-local/gateway-service:lab5-cache /path/to/gateway-service
docker compose -f docker-compose.yml -f docker-compose.lab4-mihai.yml -f docker-compose.lab5-cache.yml up -d --wait
```

The three private cache nodes share a password. The Gateway partitions entries across 128 virtual positions per node on a SHA-256 ring. On adding a node, only the keys it becomes the successor for move. The cache fills those keys on demand. Redis Cluster assigns keys to 16,384 fixed CRC16 slots. Its servers own slot migration and tell clients about moves with `MOVED` and `ASK`. [Redis Cluster specification](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)

To add a fourth node while the Gateway runs, start `cache-redis-4` explicitly using the same Compose files. Append `cache-redis-4:6379` to `docker/gateway-cache/nodes.txt` and check `docker compose logs gateway-service` for the ring size. Remove the line to move its ranges back to their successors, then stop the fourth node. Use `GATEWAY_CACHE_CONFIG_DIR` to mount a separate copy of the directory for a demo.

| Request or data | Behavior |
| --- | --- |
| Authenticated `GET /players/{id}`, `GET /rulesets/active`, `GET /rulesets/{id}` | Successful JSON responses are cached per client and request representation for 15 seconds by default. `X-Cache: MISS` identifies an eligible upstream response and `X-Cache: HIT` identifies a cached response. |
| `POST`, `PUT`, `PATCH`, `DELETE` through the Gateway | Invalidate cached GETs in the affected resource family for all clients. Reads during a write bypass the cache. |
| API keys | Positive client lookups expire after 60 seconds by default. Redis keys use an HMAC digest. |
| `POST /ws/negotiate` | Each call issues a fresh ticket. The cache holds issuance metadata until expiry. DMS validates the signed ticket and enforces single use. |

The Gateway assumes one process for write invalidation. The TTL bounds staleness for changes made through direct service access or broker deliveries. When a shard is unavailable, requests use the upstream service and the Gateway's configured authentication. The cache adds the `X-Cache` response header and keeps the existing request and response bodies.

Run [the Gateway cache Postman collection](postman/gateway-cache.postman_collection.json) with `baseUrl`, `apiKey` and `secondApiKey`. Configure the two keys as separate named clients in `GATEWAY_API_KEYS`. The collection registers a temporary player, checks cache isolation and invalidation, then removes the player.

## Redis failover · G5

`applicant-redis` and `credential-redis` are stable internal HAProxy addresses. Each points to its current Redis primary. Each group has a primary and two replicas, with separate AOF volumes. The three Sentinel instances monitor both groups and require two votes for failover. HAProxy closes old connections when a primary is removed from service. Applicant, Credential, the seed jobs and ETL keep their original hostnames and passwords.

The original Redis state volumes belong to the initial primaries. Redis and Sentinel persist their elected topology. Use a different `REDIS_HA_IP_PREFIX` for a second Compose project and keep that prefix fixed for its volumes. Fixed addresses on this private network let Sentinel vote while Docker withdraws a stopped container from DNS. Redis replication is asynchronous. `min-replicas-to-write 1` reduces the window for writes on an isolated primary. [Redis Sentinel documentation](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/)

```bash
docker compose --env-file .env.example -p pad-lab5-redis-demo up -d --wait \
  applicant-redis credential-redis redis-sentinel-1 redis-sentinel-2 redis-sentinel-3
python scripts/check_redis_failover.py --project pad-lab5-redis-demo
```

The check writes a short-lived value, waits for both replicas, stops each primary in the demo project, checks reads and writes over the original hostnames, then starts the old primaries and verifies they rejoined as replicas.
