#!/bin/sh
# Patroni runs this once, on the member that creates the cluster, with a superuser connection string
# as $1. It creates the service's login and database, which the standbys then receive by
# replication. The service's Flyway migrations create the tables when it starts.
set -eu

: "${APP_DB_NAME:?APP_DB_NAME must be set}"
: "${APP_DB_USER:?APP_DB_USER must be set}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"

psql "$1" -v ON_ERROR_STOP=1 \
    --set=app_user="$APP_DB_USER" \
    --set=app_password="$APP_DB_PASSWORD" \
    --set=app_db="$APP_DB_NAME" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';
CREATE DATABASE :"app_db" OWNER :"app_user";
SQL

echo "post-bootstrap: created database $APP_DB_NAME owned by $APP_DB_USER"
