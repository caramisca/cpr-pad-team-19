-- Data warehouse star schema for "Student ID, Please" (Lab 5, Grade 4).
-- All tables use CREATE TABLE IF NOT EXISTS so this script is idempotent and can be re-run on restart.

CREATE TABLE IF NOT EXISTS dim_players (
    player_id          UUID        PRIMARY KEY,
    discord_id         TEXT,
    display_name       TEXT,
    rank               TEXT,
    xp                 INT,
    level              INT,
    total_shifts       INT,
    correct_decisions  INT,
    incorrect_decisions INT,
    etl_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dim_rulesets (
    ruleset_id     TEXT        PRIMARY KEY,
    version        INT,
    effective_from TEXT,
    rules_json     JSONB,
    etl_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dim_students (
    student_id        TEXT        PRIMARY KEY,
    full_name         TEXT,
    faculty_code      TEXT,
    group_name        TEXT,
    study_year        INT,
    enrolment_status  TEXT,
    academic_standing TEXT,
    etl_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Static dimension: one row per microservice in the system.
-- notification_count is populated from dms-redis (discord-dms-service only).
CREATE TABLE IF NOT EXISTS dim_services (
    service_name       TEXT        PRIMARY KEY,
    description        TEXT,
    tech               TEXT,
    notification_count INT         NOT NULL DEFAULT 0,
    etl_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE dim_services ADD COLUMN IF NOT EXISTS notification_count INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS fact_decisions (
    decision_id         UUID        PRIMARY KEY,
    session_id          UUID,
    applicant_id        UUID,
    moderator_player_id UUID,
    ruleset_id          TEXT,
    action              TEXT,
    expected_action     TEXT,
    correct             BOOLEAN,
    xp_awarded          INT,
    ruleset_version     INT,
    created_at          TIMESTAMPTZ,
    evaluated_at        TIMESTAMPTZ,
    voided_at           TIMESTAMPTZ,
    etl_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fact_shifts (
    session_id           UUID        PRIMARY KEY,
    moderator_player_id  UUID,
    status               TEXT,
    applicants_processed INT,
    correct_decisions    INT,
    incorrect_decisions  INT,
    score                NUMERIC,
    started_at           TIMESTAMPTZ,
    closed_at            TIMESTAMPTZ,
    etl_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sourced from session_queue_entry (session-postgres) enriched with applicant-redis and
-- credential-redis data. deceptions (JSON array) and role come from applicant-redis (TTL 60 min,
-- NULL/empty when the entry has expired by ETL run time).
CREATE TABLE IF NOT EXISTS fact_applicants (
    applicant_id  TEXT        PRIMARY KEY,
    session_id    UUID,
    credential_id TEXT,
    deceptions    TEXT,
    role          TEXT,
    queue_position INT,
    action        TEXT,
    presented_at  TIMESTAMPTZ,
    resolved_at   TIMESTAMPTZ,
    etl_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Rename deception_type -> deceptions if upgrading from a previous ETL run.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='fact_applicants' AND column_name='deception_type') THEN
        ALTER TABLE fact_applicants RENAME COLUMN deception_type TO deceptions;
    END IF;
END $$;
ALTER TABLE fact_applicants ADD COLUMN IF NOT EXISTS deceptions TEXT;
ALTER TABLE fact_applicants ADD COLUMN IF NOT EXISTS role TEXT;
