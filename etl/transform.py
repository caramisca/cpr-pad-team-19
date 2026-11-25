import json


def transform(raw):
    cred_by_applicant = {
        str(c.get("applicantId") or ""): c
        for c in raw["credentials"]
        if c.get("applicantId")
    }
    # Applicant-redis data: keyed by applicant id, carries deceptionType and role.
    redis_applicant = {
        str(a.get("id") or a.get("applicantId") or ""): a
        for a in raw["applicants"]
        if a.get("id") or a.get("applicantId")
    }

    return {
        "dim_players":    _players(raw["players"]),
        "dim_rulesets":   _rulesets(raw["rulesets"]),
        "dim_students":   _students(raw["students"]),
        "dim_services":   _services(raw["services"], raw["dms_count"]),
        "fact_decisions": _decisions(raw["decisions"]),
        "fact_shifts":    _shifts(raw["sessions"]),
        "fact_applicants": _applicants(raw["queue"], cred_by_applicant, redis_applicant),
    }


def _players(rows):
    return [
        {
            "player_id":           str(r[0]),
            "discord_id":          r[1],
            "display_name":        r[2],
            "rank":                r[3],
            "xp":                  r[4] or 0,
            "level":               r[5] or 1,
            "total_shifts":        r[6],
            "correct_decisions":   r[7],
            "incorrect_decisions": r[8],
        }
        for r in rows
    ]


def _rulesets(docs):
    return [
        {
            "ruleset_id":    str(d["_id"]),
            "version":       d.get("version", 1),
            "effective_from": d.get("effectiveFrom"),
            "rules_json":    json.dumps(d.get("rules", [])),
        }
        for d in docs
    ]


def _students(rows):
    return [
        {
            "student_id":        r[0],
            "full_name":         r[1],
            "faculty_code":      r[2],
            "group_name":        r[3],
            "study_year":        r[4],
            "enrolment_status":  r[5],
            "academic_standing": r[6],
        }
        for r in rows
    ]


def _services(services, dms_count):
    return [
        {
            "service_name":       s[0],
            "description":        s[1],
            "tech":               s[2],
            "notification_count": dms_count if s[0] == "discord-dms-service" else 0,
        }
        for s in services
    ]


def _decisions(rows):
    return [
        {
            "decision_id":         str(r[0]),
            "session_id":          str(r[1]) if r[1] else None,
            "applicant_id":        str(r[2]) if r[2] else None,
            "moderator_player_id": str(r[3]) if r[3] else None,
            "action":              r[4],
            "created_at":          r[5],
            "voided_at":           r[6],
            "correct":             r[7],
            "expected_action":     r[8],
            "xp_awarded":          r[9],
            "ruleset_id":          r[10],
            "ruleset_version":     r[11],
            "evaluated_at":        r[12],
        }
        for r in rows
    ]


def _shifts(rows):
    return [
        {
            "session_id":           str(r[0]),
            "moderator_player_id":  str(r[1]) if r[1] else None,
            "status":               r[2],
            "started_at":           r[3],
            "closed_at":            r[4],
            "applicants_processed": r[5],
            "correct_decisions":    r[6],
            "incorrect_decisions":  r[7],
            "score":                float(r[8]) if r[8] is not None else None,
        }
        for r in rows
    ]


def _applicants(queue_rows, cred_by_applicant, redis_applicant):
    return [
        {
            "applicant_id":   str(r[2]),
            "session_id":     str(r[1]) if r[1] else None,
            "credential_id":  cred_by_applicant.get(str(r[2]), {}).get("id"),
            "deception_type": redis_applicant.get(str(r[2]), {}).get("deceptionType"),
            "role":           redis_applicant.get(str(r[2]), {}).get("role"),
            "queue_position": r[3],
            "action":         r[4],
            "presented_at":   r[5],
            "resolved_at":    r[6],
        }
        for r in queue_rows
    ]
