#!/bin/sh
# Starts one member of a replicated Redis (Lab 5, Grade 5): one primary, two replicas, three
# Sentinels that promote a replica when the primary is lost. Set in Compose:
#   REDISCLI_AUTH          the password (requirepass, masterauth; redis-cli reads it too)
#   REDIS_NODE_NAME        this member's hostname, e.g. dms-redis-2; what it announces to the others
#   REDIS_INITIAL_PRIMARY  the member that is the primary when the cluster is created, e.g. dms-redis-1
#   REDIS_MASTER_NAME      the name the Sentinels monitor it under, e.g. dms-redis
#   REDIS_SENTINELS        the Sentinels' hostnames, separated by spaces (port 26379)
#   REDIS_SENTINEL_WAIT_SECONDS  default 20; see 2.
#
# Which member is the primary changes at every failover, so it is never taken from Compose alone:
#   1. /data/redis.conf is created once, on the member's own volume. The Sentinels rewrite it
#      (CONFIG REWRITE) whenever they change the member's role, so a restarted member comes back with
#      the role it last had, not the one it was created with.
#   2. When the Sentinels already know the primary, that answer wins: a primary that was failed over
#      comes back as a replica of the new one, instead of a second primary with older data. A member
#      that already has a redis.conf waits up to REDIS_SENTINEL_WAIT_SECONDS for that answer, because
#      after "docker compose up" of a stopped stack the Sentinels start just after the members. A new
#      member (the cluster is being created) does not wait: no Sentinel knows the cluster yet.
set -eu

: "${REDISCLI_AUTH:?REDISCLI_AUTH must be set}"
: "${REDIS_NODE_NAME:?REDIS_NODE_NAME must be set}"
: "${REDIS_INITIAL_PRIMARY:?REDIS_INITIAL_PRIMARY must be set}"
: "${REDIS_MASTER_NAME:?REDIS_MASTER_NAME must be set}"
: "${REDIS_SENTINELS:?REDIS_SENTINELS must be set}"

config=/data/redis.conf
wait_seconds=${REDIS_SENTINEL_WAIT_SECONDS:-20}

if [ ! -f "$config" ]; then
    wait_seconds=0
    {
        echo "# Created by redis-node.sh on first start; rewritten by the Sentinels on failover."
        echo "dir /data"
        echo "appendonly yes"
        if [ "$REDIS_NODE_NAME" != "$REDIS_INITIAL_PRIMARY" ]; then
            echo "replicaof $REDIS_INITIAL_PRIMARY 6379"
        fi
    } > "$config"
    echo "redis-node: created $config ($REDIS_NODE_NAME, initial primary $REDIS_INITIAL_PRIMARY)"
fi

# The Sentinels answer with the primary's hostname (announce-hostnames). No answer: the cluster is
# being created, or every Sentinel is down; then the role in redis.conf stands.
ask_sentinels() {
    for sentinel in $REDIS_SENTINELS; do
        answer=$(redis-cli -h "$sentinel" -p 26379 --no-auth-warning \
            SENTINEL get-master-addr-by-name "$REDIS_MASTER_NAME" 2>/dev/null | head -n 1 || true)
        case "$answer" in
            ""|*ERR*|*NOAUTH*|*"Could not connect"*|*"(nil)"*) ;;
            *) echo "$answer"; return 0 ;;
        esac
    done
    return 0
}

primary=$(ask_sentinels)
waited=0
while [ -z "$primary" ] && [ "$waited" -lt "$wait_seconds" ]; do
    sleep 1
    waited=$((waited + 1))
    primary=$(ask_sentinels)
done

set -- redis-server "$config" \
    --requirepass "$REDISCLI_AUTH" \
    --masterauth "$REDISCLI_AUTH" \
    --replica-announce-ip "$REDIS_NODE_NAME"

if [ -n "$primary" ]; then
    if [ "$primary" = "$REDIS_NODE_NAME" ]; then
        echo "redis-node: the Sentinels name $REDIS_NODE_NAME the primary"
        set -- "$@" --replicaof no one
    else
        echo "redis-node: the Sentinels name $primary the primary; starting as its replica"
        set -- "$@" --replicaof "$primary" 6379
    fi
else
    echo "redis-node: no Sentinel answered; starting with the role in $config"
fi

exec docker-entrypoint.sh "$@"
