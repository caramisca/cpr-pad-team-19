# university-record-service — DB scripts

PostgreSQL schema and demo seed data, managed by Flyway and applied automatically on service
startup (source of truth: `services/university-record-service/src/main/resources/db/migration/`).
Copied here for visibility/testing per the CPR's Lab 1 requirement — edit the originals in the
service repo, not these copies.

- `V1__init_schema.sql` — creates `faculty`, `student_record`, `enrolment` with the foreign keys
  described in the CPR's Communication Contract.
- `V2__seed_demo_data.sql` — inserts 3 faculties and 3 students so the service has data to serve
  immediately after first boot.
