#!/bin/sh
set -eu

# Encode an authenticated replication probe as RESP. HAProxy never accepts a
# read-only replica or an isolated primary with no attached replica.
bytes=$(printf '%s' "$REDIS_PASSWORD" | wc -c)
probe_prefix=$(printf '*2\r\n$4\r\nAUTH\r\n$%d\r\n%s\r\n' "$bytes" "$REDIS_PASSWORD" | od -An -v -tx1 | tr -d ' \n')
probe_info=$(printf '*2\r\n$4\r\nINFO\r\n$11\r\nreplication\r\n' | od -An -v -tx1 | tr -d ' \n')
umask 077
cat > /tmp/redis-haproxy.cfg <<EOF
defaults
    timeout connect 2s
    timeout client 1h
    timeout server 1h
    timeout check 2s

resolvers docker
    nameserver embedded 127.0.0.11:53
    hold valid 2s

frontend readiness
    mode http
    bind 127.0.0.1:8404
    monitor-uri /healthz
    monitor fail if { nbsrv(redis-primary) lt 1 }

frontend redis
    mode tcp
    bind :6379
    default_backend redis-primary

backend redis-primary
    mode tcp
    option tcp-check
    tcp-check connect
    tcp-check send-binary $probe_prefix
    tcp-check expect string +OK
    tcp-check send-binary $probe_info
    tcp-check expect rstring role:master[[:space:][:print:]]*connected_slaves:[1-9]
    default-server inter 1s fall 1 rise 1 resolvers docker init-addr none on-marked-down shutdown-sessions
    server redis-1 $REDIS_GROUP-redis-1:6379 check
    server redis-2 $REDIS_GROUP-redis-2:6379 check
    server redis-3 $REDIS_GROUP-redis-3:6379 check
EOF
exec haproxy -W -db -f /tmp/redis-haproxy.cfg
