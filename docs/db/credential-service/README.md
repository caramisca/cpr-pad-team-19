# credential-service - DB scripts

Redis has no schema, so there is no DDL script to publish here. The service creates its keys as
credential bundles are issued. Every key is prefixed with the service's `Redis:InstanceName`,
`CredentialService:` by default:

| Key | Type | Content |
| :--- | :--- | :--- |
| `CredentialService:credential:{id}` | String (JSON) | A credential bundle, with the registrar's digest of its fields. Expires after `CredentialSettings:RetentionMinutes` (60 by default). |
| `CredentialService:credentials:by-applicant:{applicantId}` | Set | Ids of the bundles issued for an applicant. |

Copied here for visibility and testing per the CPR's Lab 1 requirement (source of truth:
`services/credential-service/scripts/seed/`). Edit the originals in the service repository, not
these copies.

- `seed.sh` - loads `credentials.redis` when Redis holds no credential bundle yet, and does nothing
  otherwise, so it is safe to run on every start. It needs only `redis-cli`, and reads
  `REDIS_HOST`, `REDIS_PORT`, `REDISCLI_AUTH` (the password) and `KEY_PREFIX` from the environment.
- `credentials.redis` - six demo bundles for the demo applicants of applicant-service: authentic
  documents, a tampered faculty, an expired enrollment confirmation, an impersonated student ID and
  a forgery with a fake authority and a fabricated hash. Their hashes are real SHA-256 digests, so
  `POST /credentials/{id}/verify-hash` answers exactly as for issued bundles.

The shared `docker-compose.yml` runs `seed.sh` as the one-shot `credential-seed` container before the
service starts, and runs Redis with append-only persistence on the `credential-redis-data` volume. To
seed a Redis by hand:

```bash
REDIS_HOST=localhost REDISCLI_AUTH=<password> sh docs/db/credential-service/seed.sh
```
