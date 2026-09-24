# applicant-service - DB scripts

Redis has no schema, so there is no DDL script to publish here. The service creates its keys as
applicants are generated. Every key is prefixed with the service's `Redis:InstanceName`,
`ApplicantService:` by default:

| Key | Type | Content |
| :--- | :--- | :--- |
| `ApplicantService:applicant:{id}` | String (JSON) | An applicant and its true identity. Expires with the applicant (60 minutes by default). |
| `ApplicantService:session:{sessionId}:applicants` | Set | Ids of the applicants of a session. Lives as long as its longest-lived applicant. |

Copied here for visibility and testing per the CPR's Lab 1 requirement (source of truth:
`services/applicant-service/scripts/seed/`). Edit the originals in the service repository, not
these copies.

- `seed.sh` - loads `applicants.redis` when Redis holds no applicant yet, and does nothing
  otherwise, so it is safe to run on every start. It needs only `redis-cli`, and reads
  `REDIS_HOST`, `REDIS_PORT`, `REDISCLI_AUTH` (the password) and `KEY_PREFIX` from the environment.
- `applicants.redis` - six demo applicants of the session `5e55a0e0-0000-4000-8000-000000000001`,
  one per kind of deception, holding the bundles seeded by credential-service and using the demo
  students of university-record-service. They do not expire before 2027-09-01.

The shared `docker-compose.yml` runs `seed.sh` as the one-shot `applicant-seed` container before the
service starts, and runs Redis with append-only persistence on the `applicant-redis-data` volume. To
seed a Redis by hand:

```bash
REDIS_HOST=localhost REDISCLI_AUTH=<password> sh docs/db/applicant-service/seed.sh
```
