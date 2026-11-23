import os
import json
import logging

import psycopg2
import pymongo
import redis

log = logging.getLogger("etl.extract")


def _pg(url):
    return psycopg2.connect(url)


def extract_players():
    try:
        with _pg(os.environ["PLAYER_POSTGRES_URL"]) as c:
            with c.cursor() as cur:
                cur.execute("""
                    SELECT p.id, p.discord_id, p.display_name, p.rank, p.xp, p.level,
                           coalesce(ps.total_shifts, 0),
                           coalesce(ps.correct_decisions, 0),
                           coalesce(ps.incorrect_decisions, 0)
                    FROM players p
                    LEFT JOIN player_stats ps ON ps.player_id = p.id
                """)
                return cur.fetchall()
    except Exception as e:
        log.warning("extract_players failed: %s", e)
        return []


def extract_sessions():
    try:
        with _pg(os.environ["SESSION_POSTGRES_URL"]) as c:
            with c.cursor() as cur:
                cur.execute("""
                    SELECT s.id, s.moderator_id, s.status, s.started_at, s.closed_at,
                           coalesce(ss.applicants_processed, 0),
                           coalesce(ss.correct_decisions, 0),
                           coalesce(ss.incorrect_decisions, 0),
                           ss.score
                    FROM sessions s
                    LEFT JOIN session_summary ss ON ss.session_id = s.id
                """)
                return cur.fetchall()
    except Exception as e:
        log.warning("extract_sessions failed: %s", e)
        return []


def extract_queue():
    try:
        with _pg(os.environ["SESSION_POSTGRES_URL"]) as c:
            with c.cursor() as cur:
                cur.execute("""
                    SELECT id, session_id, applicant_id, queue_position,
                           action, presented_at, resolved_at
                    FROM session_queue_entry
                """)
                return cur.fetchall()
    except Exception as e:
        log.warning("extract_queue failed: %s", e)
        return []


def extract_decisions():
    try:
        with _pg(os.environ["MODERATION_POSTGRES_URL"]) as c:
            with c.cursor() as cur:
                cur.execute("""
                    SELECT d.id, d.session_id, d.applicant_id, d.moderator_id, d.action,
                           d.created_at, d.voided_at,
                           v.correct, v.expected_action, v.xp_awarded,
                           v.ruleset_id::text, v.ruleset_version, v.evaluated_at
                    FROM decision d
                    LEFT JOIN verdict v ON v.decision_id = d.id
                """)
                return cur.fetchall()
    except Exception as e:
        log.warning("extract_decisions failed: %s", e)
        return []


def extract_students():
    try:
        with _pg(os.environ["RECORD_POSTGRES_URL"]) as c:
            with c.cursor() as cur:
                cur.execute("""
                    SELECT sr.student_id, sr.full_name,
                           e.faculty_code, e.group_name, e.study_year,
                           e.enrolment_status, e.academic_standing
                    FROM student_record sr
                    LEFT JOIN enrolment e ON e.student_id = sr.student_id
                """)
                return cur.fetchall()
    except Exception as e:
        log.warning("extract_students failed: %s", e)
        return []


def extract_rulesets():
    try:
        client = pymongo.MongoClient(
            os.environ["RULES_MONGO_URI"], serverSelectionTimeoutMS=5000
        )
        db = client.get_default_database()
        docs = list(db.rulesets.find({}, {"_id": 1, "version": 1, "effectiveFrom": 1, "rules": 1}))
        client.close()
        return docs
    except Exception as e:
        log.warning("extract_rulesets failed: %s", e)
        return []


def extract_applicants():
    try:
        r = redis.from_url(os.environ["APPLICANT_REDIS_URL"], decode_responses=True)
        result = []
        for key in r.keys("ApplicantService:applicant:*"):
            raw = r.get(key)
            if raw:
                result.append(json.loads(raw))
        return result
    except Exception as e:
        log.warning("extract_applicants failed: %s", e)
        return []


def extract_credentials():
    try:
        r = redis.from_url(os.environ["CREDENTIAL_REDIS_URL"], decode_responses=True)
        result = []
        for key in r.keys("CredentialService:credential:*"):
            raw = r.get(key)
            if raw:
                result.append(json.loads(raw))
        return result
    except Exception as e:
        log.warning("extract_credentials failed: %s", e)
        return []


def extract_dms_notification_count():
    try:
        r = redis.from_url(os.environ["DMS_REDIS_URL"], decode_responses=True)
        return len(r.keys("dms:notification:*"))
    except Exception as e:
        log.warning("extract_dms_notification_count failed: %s", e)
        return 0


STATIC_SERVICES = [
    ("gateway-service",                    "Single ingress proxy, circuit breaker, log aggregation",   "Python/FastAPI"),
    ("message-broker",                     "Durable async event bus over gRPC",                        "Python/gRPC"),
    ("service-discovery",                  "Service registry with health polling and alerts",           "Python/FastAPI"),
    ("server-rules-service",               "Rulesets and versioning (MongoDB replica set)",             "Java/Spring Boot"),
    ("university-record-service",          "Authoritative student registry (Patroni HA)",               "Java/Spring Boot"),
    ("server-moderation-session-service",  "Shift lifecycle and SSE stream",                            "Java/Spring Boot"),
    ("player-service",                     "Moderator XP, rank and lifetime stats (Patroni HA)",        "Java/Spring Boot"),
    ("applicant-service",                  "Ephemeral applicant generation (Redis Sentinel)",           "C#/.NET 8"),
    ("credential-service",                 "Credential bundles and integrity hashes (Redis Sentinel)",  "C#/.NET 8"),
    ("moderation-service",                 "Decision evaluation with transactional outbox",             "C#/.NET 8"),
    ("discord-dms-service",                "Outbound DMs and WebSocket moderation chat",                "C#/.NET 8"),
]


def extract_all():
    return {
        "players":        extract_players(),
        "sessions":       extract_sessions(),
        "queue":          extract_queue(),
        "decisions":      extract_decisions(),
        "students":       extract_students(),
        "rulesets":       extract_rulesets(),
        "applicants":     extract_applicants(),
        "credentials":    extract_credentials(),
        "dms_count":      extract_dms_notification_count(),
        "services":       STATIC_SERVICES,
    }
