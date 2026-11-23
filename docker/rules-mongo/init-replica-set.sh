#!/usr/bin/env bash
set -euo pipefail

mongo() {
    mongosh --host rules-mongo-1:27017 --quiet \
        -u "$RULES_MONGO_USERNAME" -p "$RULES_MONGO_PASSWORD" --authenticationDatabase admin "$@"
}

for ((attempt = 0; attempt < 40; attempt++)); do
    if mongo --eval 'db.adminCommand({ping:1})' >/dev/null 2>&1 && mongo --eval '
            try {
                const result = rs.initiate({_id: "rs0", members: [
                    {_id: 0, host: "rules-mongo-1:27017", priority: 2},
                    {_id: 1, host: "rules-mongo-2:27017"},
                    {_id: 2, host: "rules-mongo-3:27017"}
                ]});
                if (!result.ok) throw Error(JSON.stringify(result));
            } catch (error) {
                if (error.codeName !== "AlreadyInitialized") throw error;
            }
        '; then
        break
    fi
    sleep 2
done

for ((attempt = 0; attempt < 40; attempt++)); do
    if mongo --eval 'if (!rs.status().members.some(member => member.stateStr === "PRIMARY")) quit(1)' >/dev/null 2>&1; then
        exit 0
    fi
    sleep 2
done

echo 'Mongo replica set did not elect a primary' >&2
exit 1
