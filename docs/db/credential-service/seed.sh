#!/bin/sh
# Populates the credential-service Redis with the demo credential bundles in credentials.redis,
# but only when it holds no credential bundle yet, so running it again never overwrites data.
#
# Runs anywhere redis-cli is available (the shared Docker Compose file runs it in a redis:7.4-alpine
# container). Configuration, all optional:
#   REDIS_HOST     Redis host                        (default: localhost)
#   REDIS_PORT     Redis port                        (default: 6379)
#   REDISCLI_AUTH  Redis password, read by redis-cli (default: none)
#   KEY_PREFIX     the service's Redis:InstanceName  (default: CredentialService:)
#   SEED_FILE      commands to load                  (default: credentials.redis next to this script)
set -eu

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
KEY_PREFIX="${KEY_PREFIX:-CredentialService:}"
SEED_FILE="${SEED_FILE:-$(dirname "$0")/credentials.redis}"

cli() {
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "$@"
}

count_bundles() {
    cli --scan --pattern "${KEY_PREFIX}credential:*" | wc -l | tr -d ' '
}

attempt=0
until [ "$(cli ping 2>/dev/null)" = "PONG" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "seed: Redis at ${REDIS_HOST}:${REDIS_PORT} is not answering (is REDISCLI_AUTH set?)" >&2
        exit 1
    fi
    sleep 1
done

existing=$(count_bundles)
if [ "$existing" -gt 0 ]; then
    echo "seed: Redis already holds ${existing} credential bundle(s); nothing to do."
    exit 0
fi

replies=$(grep -v -e '^#' -e '^[[:space:]]*$' "$SEED_FILE" | sed "s|__PREFIX__|${KEY_PREFIX}|g" | cli)
if printf '%s\n' "$replies" | grep -q -e '^ERR' -e '^(error)' -e 'NOAUTH' -e 'WRONGPASS'; then
    echo "seed: Redis rejected a command:" >&2
    printf '%s\n' "$replies" >&2
    exit 1
fi

echo "seed: loaded $(count_bundles) demo credential bundle(s)."
