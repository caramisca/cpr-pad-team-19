#!/bin/sh
# Starts one Redis Sentinel of a replicated Redis (Lab 5, Grade 5). Three Sentinels watch the primary;
# when at least REDIS_QUORUM of them cannot reach it for REDIS_DOWN_AFTER_MS, they elect one of them,
# which promotes the most up-to-date replica and points the other members (and, once it is back,
# the old primary) at it. Clients ask any Sentinel for the current primary. Set in Compose:
#   REDISCLI_AUTH          the password of the Redis members, and of the Sentinels themselves
#   REDIS_SENTINEL_ADDRESS this Sentinel's fixed IPv4 address, e.g. 172.30.58.21
#   REDIS_MASTER_NAME      the name it monitors the primary under, e.g. dms-redis
#   REDIS_INITIAL_PRIMARY  the fixed address of the member that is the primary when the cluster is created
#   REDIS_MEMBERS          the fixed addresses of all members, separated by spaces
#   REDIS_QUORUM           default 2 (of 3)
#   REDIS_DOWN_AFTER_MS    default 5000
#   REDIS_FAILOVER_TIMEOUT_MS  default 20000
#   REDIS_MEMBER_WAIT_SECONDS  default 45; see "Which member is the primary" below
#
# Addresses, not hostnames. Docker removes a stopped container from its DNS, and the Sentinel resolves
# hostnames with a blocking lookup on its only thread, once a second, for the member it cannot reach.
# For a name Docker no longer knows, the lookup is forwarded to the host's resolver and can take
# seconds, so the Sentinel's timer falls behind, it enters TILT mode and neither votes nor fails over
# until the stopped member comes back (#320). With an IPv4 address the Sentinel does no lookup at all,
# and Compose pins each member's address on the dms-redis-ha network, so a restarted member keeps it.
#
# The Sentinel rewrites its configuration with what it learns (the current primary, the replicas,
# the other Sentinels), so it lives on the Sentinel's own volume and is created only once: after a
# restart the Sentinel still knows which member is the primary.
set -eu

: "${REDISCLI_AUTH:?REDISCLI_AUTH must be set}"
: "${REDIS_SENTINEL_ADDRESS:?REDIS_SENTINEL_ADDRESS must be set}"
: "${REDIS_MASTER_NAME:?REDIS_MASTER_NAME must be set}"
: "${REDIS_INITIAL_PRIMARY:?REDIS_INITIAL_PRIMARY must be set}"
: "${REDIS_MEMBERS:?REDIS_MEMBERS must be set}"

config=/data/sentinel.conf
wait_seconds=${REDIS_MEMBER_WAIT_SECONDS:-45}

# A configuration from before #320 names the members by hostname. Create it again with addresses;
# the old file stays next to it for reference.
if [ -f "$config" ] && grep -q '^sentinel resolve-hostnames yes' "$config"; then
    mv "$config" "$config.hostnames"
    echo "sentinel: $config named the members by hostname; creating it again with addresses (old file: $config.hostnames)"
fi

# The member that is the primary right now and has at least one replica attached, or nothing. With
# "any", a primary without replicas counts too. A member that was the primary when it was stopped
# comes back as a primary without replicas, so the first pass does not pick it over the real one.
find_primary() {
    for member in $REDIS_MEMBERS; do
        info=$(timeout 2 redis-cli -h "$member" -p 6379 --no-auth-warning INFO replication 2>/dev/null | tr -d '\r' || true)
        case "$info" in
            *role:master*) ;;
            *) continue ;;
        esac
        replicas=$(echo "$info" | sed -n 's/^connected_slaves://p')
        if [ "$1" = any ] || [ "${replicas:-0}" -gt 0 ]; then
            echo "$member"
            return 0
        fi
    done
    return 0
}

if [ ! -f "$config" ]; then
    # Which member is the primary: on a new cluster, the initial primary as soon as its replicas are
    # attached. When only this Sentinel's volume is new (or its configuration was created again
    # above), the members may have failed over since the cluster was created, so ask them. A member
    # with a configuration of its own waits up to 20 s for the Sentinels before it starts
    # (redis-node.sh), hence the longer wait here.
    primary=$(find_primary replicas)
    waited=0
    while [ -z "$primary" ] && [ "$waited" -lt "$wait_seconds" ]; do
        sleep 1
        waited=$((waited + 1))
        primary=$(find_primary replicas)
    done
    if [ -z "$primary" ]; then
        primary=$(find_primary any)
    fi
    primary=${primary:-$REDIS_INITIAL_PRIMARY}

    cat > "$config" <<EOF
# Created by sentinel.sh on first start; rewritten by the Sentinel itself afterwards.
port 26379
dir /data
sentinel announce-ip $REDIS_SENTINEL_ADDRESS
requirepass $REDISCLI_AUTH
sentinel sentinel-pass $REDISCLI_AUTH
sentinel monitor $REDIS_MASTER_NAME $primary 6379 ${REDIS_QUORUM:-2}
sentinel auth-pass $REDIS_MASTER_NAME $REDISCLI_AUTH
sentinel down-after-milliseconds $REDIS_MASTER_NAME ${REDIS_DOWN_AFTER_MS:-5000}
sentinel failover-timeout $REDIS_MASTER_NAME ${REDIS_FAILOVER_TIMEOUT_MS:-20000}
sentinel parallel-syncs $REDIS_MASTER_NAME 1
EOF
    chmod 600 "$config"
    echo "sentinel: created $config (monitoring $REDIS_MASTER_NAME at $primary)"
fi

exec docker-entrypoint.sh redis-sentinel "$config"
