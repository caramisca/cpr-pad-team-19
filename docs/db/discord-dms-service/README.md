# discord-dms-service - DB scripts

Redis has no schema, so there is no DDL script to publish here, and the service needs no seed
data. It creates its keys as notifications are queued, events are consumed, chat tickets are used,
and sagas call it. Every key is prefixed with `dms:`:

| Key | Type | Content |
| :--- | :--- | :--- |
| `dms:notification:{id}` | String (JSON) | A notification with its delivery status. Expires 7 days after it becomes `SENT` or `FAILED`. |
| `dms:queue` | Sorted set | Ids of the notifications waiting for delivery, scored by when the next attempt is due. |
| `dms:event:{eventId}` | String (JSON) | The notifications created for a consumed event, kept for 7 days to recognise a redelivery. |
| `dms:session:{sessionId}` | String | The moderator of an open session, from `session.started` until `session.closed`, at most 24 hours. |
| `dms:sessions:open` | Set | Ids of the open sessions, used to notify every moderator of a `ruleset.updated`. |
| `dms:ws-ticket:{jti}` | String | The user id of a chat ticket that has opened a connection, so that it cannot open another. Expires 10 seconds after the ticket. |
| `dms:delivery:rate-limit` | Hash | The Discord rate limit bucket every instance takes from: the tokens left and when the current refill period started. Expires once the bucket would be full again. |
| `dms:saga:{sagaId}` | String (JSON) | Lab 5: the receipt of a saga's notification step (`contracts/saga.md`): queued, with the notification id, or cancelled, with the id or none (a tombstone). Expires after 7 days. |
| `dms:delivering:{id}` | String | Lab 5: set by the delivery worker while it sends the notification to Discord, so that a saga's cancellation waits for the outcome. Expires after 30 seconds and is deleted once the outcome is stored. |

Chat messages are not stored: they pass between instances on the Redis pub/sub channel `dms:chat`,
together with the notices that close the chat of a session.

The shared `docker-compose.yml` runs Redis with append-only persistence, so queued notifications,
retries, and processed event ids survive a restart. Since Lab 5 it is replicated: three members
(`dms-redis-1/2/3`, one primary and two replicas, each on its own `dms-redis-<n>-data` volume) and
three Sentinels (`dms-redis-sentinel-1/2/3`), all on fixed addresses on the private network
`dms-redis-ha`. The service and ETL connect through the `dms-redis` HAProxy, which forwards to the
current primary. The first local crash test found that the Sentinels, which then named the members
by hostname, lost DNS resolution of the stopped primary and did not fail over; they now know the
members by address ([#320](https://github.com/caramisca/cpr-pad-team-19/issues/320)). See
[`docs/LAB_5_MODERATION_DMS_FAILOVER.md`](../../LAB_5_MODERATION_DMS_FAILOVER.md).
