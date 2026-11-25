#!/bin/sh
# Starts one Redis Sentinel of a replicated Redis (Lab 5, Grade 5). Three Sentinels watch the primary;
# when at least REDIS_QUORUM of them cannot reach it for REDIS_DOWN_AFTER_MS, they elect one of them,
# which promotes the most up-to-date replica and points the other members (and, once it is back,
# the old primary) at it. Clients ask any Sentinel for the current primary. Set in Compose:
#   REDISCLI_AUTH          the password of the Redis members, and of the Sentinels themselves
#   REDIS_SENTINEL_NAME    this Sentinel's hostname, e.g. dms-redis-sentinel-1
#   REDIS_MASTER_NAME      the name it monitors the primary under, e.g. dms-redis
#   REDIS_INITIAL_PRIMARY  the member that is the primary when the cluster is created
#   REDIS_QUORUM           default 2 (of 3)
#   REDIS_DOWN_AFTER_MS    default 5000
#   REDIS_FAILOVER_TIMEOUT_MS  default 20000
#
# The Sentinel rewrites its configuration with what it learns (the current primary, the replicas,
# the other Sentinels), so it lives on the Sentinel's own volume and is created only once: after a
# restart the Sentinel still knows which member is the primary.
set -eu

: "${REDISCLI_AUTH:?REDISCLI_AUTH must be set}"
: "${REDIS_SENTINEL_NAME:?REDIS_SENTINEL_NAME must be set}"
: "${REDIS_MASTER_NAME:?REDIS_MASTER_NAME must be set}"
: "${REDIS_INITIAL_PRIMARY:?REDIS_INITIAL_PRIMARY must be set}"

config=/data/sentinel.conf

if [ ! -f "$config" ]; then
    # resolve-hostnames comes before the monitor line, which names the primary by hostname: Docker
    # gives a restarted container a new IP address, never a new name.
    cat > "$config" <<EOF
# Created by sentinel.sh on first start; rewritten by the Sentinel itself afterwards.
port 26379
dir /data
sentinel resolve-hostnames yes
sentinel announce-hostnames yes
sentinel announce-ip $REDIS_SENTINEL_NAME
requirepass $REDISCLI_AUTH
sentinel sentinel-pass $REDISCLI_AUTH
sentinel monitor $REDIS_MASTER_NAME $REDIS_INITIAL_PRIMARY 6379 ${REDIS_QUORUM:-2}
sentinel auth-pass $REDIS_MASTER_NAME $REDISCLI_AUTH
sentinel down-after-milliseconds $REDIS_MASTER_NAME ${REDIS_DOWN_AFTER_MS:-5000}
sentinel failover-timeout $REDIS_MASTER_NAME ${REDIS_FAILOVER_TIMEOUT_MS:-20000}
sentinel parallel-syncs $REDIS_MASTER_NAME 1
EOF
    chmod 600 "$config"
    echo "sentinel: created $config (monitoring $REDIS_MASTER_NAME at $REDIS_INITIAL_PRIMARY)"
fi

exec docker-entrypoint.sh redis-sentinel "$config"
