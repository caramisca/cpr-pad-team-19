# PostgreSQL 16 with Patroni (Lab 5, Grade 5: database replication and failover).
#
# One container = one member of a replicated cluster: Patroni starts PostgreSQL, keeps the cluster's
# state in etcd, makes exactly one member the primary and the others streaming standbys, and promotes
# a standby when the primary is lost. Used by player-postgres-1..3 and session-postgres-1..3 in the
# root docker-compose.yml; HAProxy (haproxy-postgres.cfg) sends clients to whichever member is the
# primary. Settings: patroni.yml here plus the PATRONI_* and APP_DB_* variables set in Compose.
FROM postgres:16.16-bookworm

ARG PATRONI_VERSION=4.1.5
ARG PSYCOPG_VERSION=3.3.6

# Patroni runs in its own virtual environment, so the image's system Python stays untouched; curl is
# for the Compose healthcheck (Patroni's REST API on 8008).
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv curl \
    && python3 -m venv /opt/patroni \
    && /opt/patroni/bin/pip install --no-cache-dir \
        "patroni[etcd3]==${PATRONI_VERSION}" "psycopg[binary]==${PSYCOPG_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/postgresql/patroni \
    && chown postgres:postgres /var/lib/postgresql/patroni \
    && chmod 0700 /var/lib/postgresql/patroni

ENV PATH=/opt/patroni/bin:$PATH

COPY --chown=postgres:postgres patroni.yml /etc/patroni/patroni.yml
COPY --chown=postgres:postgres --chmod=0755 post-bootstrap.sh /etc/patroni/post-bootstrap.sh

USER postgres
WORKDIR /var/lib/postgresql

# 5432: PostgreSQL. 8008: Patroni's REST API (/primary, /replica, /health), read by HAProxy.
EXPOSE 5432 8008

ENTRYPOINT ["patroni", "/etc/patroni/patroni.yml"]
