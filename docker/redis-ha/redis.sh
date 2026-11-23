#!/bin/sh
set -eu

cd /data
quote_password() {
    printf '"'
    printf '%s' "$1" | sed 's/[\\"]/\\&/g'
    printf '"'
}

# Redis and Sentinel rewrite their config after promotion; keep it with the data.
if [ "$1" = sentinel ]; then
    if [ ! -f sentinel.conf ]; then
        umask 077
        cat > sentinel.conf.tmp <<EOF
port 26379
protected-mode no
sentinel announce-ip $REDIS_NODE_ADDRESS
sentinel monitor applicant $REDIS_HA_IP_PREFIX.11 6379 2
sentinel auth-pass applicant $(quote_password "$APPLICANT_REDIS_PASSWORD")
sentinel down-after-milliseconds applicant 5000
sentinel failover-timeout applicant 30000
sentinel monitor credential $REDIS_HA_IP_PREFIX.21 6379 2
sentinel auth-pass credential $(quote_password "$CREDENTIAL_REDIS_PASSWORD")
sentinel down-after-milliseconds credential 5000
sentinel failover-timeout credential 30000
EOF
        chown redis:redis sentinel.conf.tmp
        mv sentinel.conf.tmp sentinel.conf
    fi
    exec docker-entrypoint.sh redis-server /data/sentinel.conf --sentinel
fi

if [ ! -f redis.conf ]; then
    umask 077
    password=$(quote_password "$REDISCLI_AUTH")
    cat > redis.conf.tmp <<EOF
appendonly yes
requirepass $password
masterauth $password
replica-announce-ip $REDIS_NODE_ADDRESS
min-replicas-to-write 1
min-replicas-max-lag 5
EOF
    if [ "$REDIS_NODE_ADDRESS" != "$REDIS_INITIAL_PRIMARY" ]; then
        printf 'replicaof %s 6379\n' "$REDIS_INITIAL_PRIMARY" >> redis.conf.tmp
    fi
    chown redis:redis redis.conf.tmp
    mv redis.conf.tmp redis.conf
fi
exec docker-entrypoint.sh redis-server /data/redis.conf
