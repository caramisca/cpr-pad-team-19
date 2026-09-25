# discord-dms-service - DB scripts

Redis has no schema, so there is no DDL script to publish here, and the service needs no seed
data. It creates its keys as notifications are queued and events are consumed. Every key is
prefixed with `dms:`:

| Key | Type | Content |
| :--- | :--- | :--- |
| `dms:notification:{id}` | String (JSON) | A notification with its delivery status. Expires 7 days after it becomes `SENT` or `FAILED`. |
| `dms:queue` | Sorted set | Ids of the notifications waiting for delivery, scored by when the next attempt is due. |
| `dms:event:{eventId}` | String (JSON) | The notifications created for a consumed event, kept for 7 days to recognise a redelivery. |
| `dms:session:{sessionId}` | String | The moderator of an open session, from `session.started` until `session.closed`, at most 24 hours. |
| `dms:sessions:open` | Set | Ids of the open sessions, used to notify every moderator of a `ruleset.updated`. |

The shared `docker-compose.yml` runs Redis with append-only persistence on the `dms-redis-data`
volume, so queued notifications, retries, and processed event ids survive a restart.
