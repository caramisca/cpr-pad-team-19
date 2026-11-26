import os
import pathlib
import logging

import psycopg2
import psycopg2.extras

log = logging.getLogger("etl.load")


def _conn():
    return psycopg2.connect(os.environ["WAREHOUSE_DB_URL"])


def ensure_schema():
    ddl = (pathlib.Path(__file__).parent / "schema.sql").read_text()
    with _conn() as c:
        with c.cursor() as cur:
            cur.execute(ddl)
        c.commit()
    log.info("Warehouse schema ready")


def _upsert(conn, table, rows, pk, columns):
    if not rows:
        return
    placeholders = ", ".join(["%s"] * len(columns))
    updates = ", ".join(f"{col} = EXCLUDED.{col}" for col in columns if col != pk)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk}) DO UPDATE SET {updates}, etl_at = now()"
    )
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            sql,
            [[row.get(col) for col in columns] for row in rows],
            page_size=500,
        )
    log.info("Upserted %d rows into %s", len(rows), table)


def load_all(data):
    with _conn() as conn:
        _upsert(conn, "dim_players", data["dim_players"], "player_id",
                ["player_id", "discord_id", "display_name", "rank", "xp", "level",
                 "total_shifts", "correct_decisions", "incorrect_decisions"])

        _upsert(conn, "dim_rulesets", data["dim_rulesets"], "ruleset_id",
                ["ruleset_id", "version", "effective_from", "rules_json"])

        _upsert(conn, "dim_students", data["dim_students"], "student_id",
                ["student_id", "full_name", "faculty_code", "group_name",
                 "study_year", "enrolment_status", "academic_standing"])

        _upsert(conn, "dim_services", data["dim_services"], "service_name",
                ["service_name", "description", "tech", "notification_count"])

        _upsert(conn, "fact_decisions", data["fact_decisions"], "decision_id",
                ["decision_id", "session_id", "applicant_id", "moderator_player_id",
                 "action", "created_at", "voided_at", "correct", "expected_action",
                 "xp_awarded", "ruleset_id", "ruleset_version", "evaluated_at"])

        _upsert(conn, "fact_shifts", data["fact_shifts"], "session_id",
                ["session_id", "moderator_player_id", "status", "started_at", "closed_at",
                 "applicants_processed", "correct_decisions", "incorrect_decisions", "score"])

        _upsert(conn, "fact_applicants", data["fact_applicants"], "applicant_id",
                ["applicant_id", "session_id", "credential_id", "deceptions", "role",
                 "queue_position", "action", "presented_at", "resolved_at"])

        conn.commit()
