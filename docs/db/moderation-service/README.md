# moderation-service - DB scripts

PostgreSQL schema of `moderation-service`, managed by EF Core migrations and applied automatically
when the service starts (source of truth: `services/moderation-service/src/ModerationService/Persistence/Migrations/`).
Copied here for visibility and testing per the CPR's Lab 1 requirement. Edit the migrations in the
service repository, not this copy.

- `schema.sql` - creates `decision`, `verdict`, `violation`, and `outbox_message`, their indexes,
  and the `__EFMigrationsHistory` table that records the applied migration. It is the idempotent
  script generated from the migrations of version `0.2.0`:

  ```bash
  cd services/moderation-service
  dotnet tool restore
  dotnet ef migrations script --idempotent --project src/ModerationService
  ```

  Every step is skipped when the migration is already recorded, so the script is safe to run more
  than once, and the service does not apply the migration again on a database created with it.

There is no seed script: decisions are recorded through `POST /decisions`, and the credentials,
ruleset, and registry records they are evaluated against belong to other services.
