"""Check the decision-verdict saga the Gateway coordinates (Lab 5, Grade 9) on a running Compose project.

POST /sagas/decision-verdicts records a moderation decision (moderation-service) and queues the
applicant's VERDICT direct message (discord-dms-service) as one saga: every step a local transaction
of its participant, a failure undone by compensations in reverse order (contracts/saga.md,
docs/LAB_5_SAGA.md). Six scenarios:

1. complete: 201 COMPLETED; the decision is CONFIRMED, the VERDICT DM queued for the applicant with
   the saga's id in its metadata, and the saga's log records every step;
2. replay: the same Idempotency-Key returns the same saga, and the session still has one decision;
3. refused: an unknown credential -> moderation refuses step 1 (422), the saga is FAILED and nothing
   is left behind; a body that is not a JSON object -> 400 VALIDATION_ERROR and no saga;
4. compensation: every discord-dms-service instance stopped -> step 2 cannot be done, the saga is
   COMPENSATING and the decision stays PENDING (semantic lock: PATCH -> 409 DECISION_PENDING) while
   the DMS is down; once it is back, the notification is cancelled, then the decision voided:
   COMPENSATED, the decision 404, and both participants refuse a late forward call (409
   SAGA_COMPENSATED, the tombstones);
5. recovery: the Gateway killed between step 1 and step 2 -> after its restart it resumes the saga
   from its log and completes it, with one decision and one DM;
6. api: GET /sagas/{unknown} -> 404 SAGA_NOT_FOUND, a non-UUID -> 400, the listing filters by state,
   and the participants' /internal/sagas/... routes are not reachable through the Gateway (404
   ROUTE_NOT_FOUND).

Scenario 5 kills the Gateway between two steps, so the Gateway must run with
GATEWAY_SAGA_STEP_DELAY_SECONDS (e.g. 4): it then waits that long before each step. Without it the
scenario is skipped (reported, not failed). Standard library only; every HTTP call runs inside the
service-discovery container against the Gateway's internal port 8090 (no API key) or the
participants themselves, so no .env is read and no secret printed. It creates decisions of its own,
for new sessions, with the seeded applicant and credential of the Postman collections.

    python3 scripts/check_saga.py --evidence docs/evidence/lab5-saga.json
    python3 scripts/check_saga.py --scenario compensation
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_postgres_failover import Compose  # noqa: E402  (Daria's Grade 5 check)

GATEWAY_URL = "http://gateway-service:8090"
MODERATION_URL = "http://moderation-service:8087"
DMS_URL = "http://discord-dms-service:8088"
DMS_SERVICES = ("discord-dms-service", "discord-dms-service-replica")
APPLICANT_ID = "a0000000-0000-4000-8000-000000000001"
CREDENTIAL_ID = "c0000000-0000-4000-8000-000000000001"
UNKNOWN_APPLICANT_ID = "a0000000-0000-4000-8000-000000000099"
UNKNOWN_CREDENTIAL_ID = "c0000000-0000-4000-8000-000000000099"
FINAL_STATES = ("COMPLETED", "FAILED", "COMPENSATED")

# One HTTP request from inside the Compose network; prints {"status", "headers", "body"} as JSON.
HTTP_SCRIPT = r"""
import json, sys, urllib.request, urllib.error
method, url, body, headers, timeout = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4]), float(sys.argv[5])
data = body.encode() if body else None
request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **headers})
keep = ("location", "retry-after", "idempotent-replay")
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status, raw, got = response.status, response.read(), response.headers
except urllib.error.HTTPError as error:
    status, raw, got = error.code, error.read(), error.headers
except Exception as error:
    status, raw, got = 0, json.dumps({"error": "NO_ANSWER", "message": str(error)}).encode(), {}
try:
    parsed = json.loads(raw) if raw else None
except ValueError:
    parsed = raw.decode(errors="replace")
print(json.dumps({"status": status, "headers": {k.lower(): v for k, v in got.items() if k.lower() in keep}, "body": parsed}))
"""


class Answer:
    def __init__(self, status: int, headers: dict, body: object) -> None:
        self.status, self.headers, self.body = status, headers, body

    def field(self, name: str):
        return self.body.get(name) if isinstance(self.body, dict) else None

    def __repr__(self) -> str:
        return f"{self.status} {json.dumps(self.body)[:300]}"


class Check:
    def __init__(self, compose: Compose) -> None:
        self.compose = compose

    def http(self, method: str, url: str, body: object = None, headers: dict | None = None,
             timeout: float = 15, raw_body: str | None = None) -> Answer:
        payload = raw_body if raw_body is not None else (json.dumps(body) if body is not None else "")
        result = self.compose.run("exec", "-T", "service-discovery", "python", "-c", HTTP_SCRIPT, method, url, payload,
                                  json.dumps(headers or {}), str(timeout), check=False, timeout=timeout + 15)
        if result.returncode != 0:
            raise RuntimeError(f"{method} {url}: {result.stderr.strip()}")
        answer = json.loads(result.stdout)
        return Answer(answer["status"], answer["headers"], answer["body"])

    def env(self, service: str, name: str) -> str:
        return self.compose.run("exec", "-T", service, "printenv", name, check=False).stdout.strip()

    # -- the saga API ---------------------------------------------------------------------------------

    def start(self, request: dict, key: str | None = None, timeout: float = 20) -> Answer:
        headers = {"X-Request-Id": f"saga-check-{uuid.uuid4().hex[:12]}"}
        if key:
            headers["Idempotency-Key"] = key
        return self.http("POST", f"{GATEWAY_URL}/sagas/decision-verdicts", request, headers, timeout=timeout)

    def saga(self, saga_id: str) -> dict | None:
        answer = self.http("GET", f"{GATEWAY_URL}/sagas/{saga_id}", timeout=5)
        return answer.body if answer.status == 200 else None

    def finished(self, saga_id: str, timeout: float) -> dict:
        return self.wait_until(f"saga {saga_id} in a final state",
                               lambda: (lambda s: s if s and s["state"] in FINAL_STATES else None)(self.saga(saga_id)),
                               timeout=timeout)

    def saga_ids(self) -> set[str]:
        """The IDs of the newest sagas, read before the check starts one of its own."""
        answer = self.http("GET", f"{GATEWAY_URL}/sagas?limit=20", timeout=5)
        if answer.status != 200:
            raise RuntimeError(f"GET /sagas answered {answer}")
        return {s["sagaId"] for s in answer.body["sagas"]}

    def newest_saga(self, known: set[str]) -> dict | None:
        """The newest saga not in ``known`` (the check runs one saga at a time), with its steps.

        One call, without the log, so that a poll stays short. Matched by ID, not by ``createdAt``:
        the clock of the Docker VM may differ from this host's."""
        answer = self.http("GET", f"{GATEWAY_URL}/sagas?limit=5", timeout=5)
        if answer.status != 200:
            return None
        return next((s for s in answer.body["sagas"] if s["sagaId"] not in known), None)

    # -- the participants' own state --------------------------------------------------------------

    def decision(self, decision_id: str) -> Answer:
        return self.http("GET", f"{GATEWAY_URL}/decisions/{decision_id}")

    def session_decisions(self, session_id: str) -> list[dict]:
        answer = self.http("GET", f"{GATEWAY_URL}/sessions/{session_id}/decisions")
        if answer.status != 200:
            raise RuntimeError(f"GET /sessions/{session_id}/decisions answered {answer}")
        return answer.body["decisions"]

    def notification(self, notification_id: str) -> Answer:
        return self.http("GET", f"{GATEWAY_URL}/notifications/{notification_id}")

    def wait_until(self, what: str, condition, timeout: float, interval: float = 1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = condition()
            except RuntimeError:
                value = None
            if value:
                return value
            time.sleep(interval)
        raise RuntimeError(f"{what}: not within {timeout:g} s")


def new_request(applicant: str = APPLICANT_ID, credential: str = CREDENTIAL_ID) -> dict:
    return {"sessionId": str(uuid.uuid4()), "applicantId": applicant, "credentialId": credential,
            "moderatorId": str(uuid.uuid4()), "action": "ACCEPT"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def step_states(document: dict) -> dict[str, str]:
    return {step["name"]: step["state"] for step in document.get("steps", [])}


def expect(result: dict, name: str, condition: bool, detail: object = None) -> None:
    result.setdefault("checks", {})[name] = bool(condition)
    if not condition:
        result["errors"].append(f"{name}" + (f": {detail}" if detail is not None else ""))


def run_to_end(check: Check, answer: Answer, timeout: float = 60) -> dict:
    """The saga the POST answered, followed until it is final when the POST answered 202 (still running)."""
    saga_id = answer.field("sagaId")
    if not saga_id:
        raise RuntimeError(f"POST /sagas/decision-verdicts answered without a sagaId: {answer}")
    if answer.status == 202:
        return check.finished(saga_id, timeout)
    return check.saga(saga_id) or answer.body


# -- scenarios ---------------------------------------------------------------------------------------

def complete(check: Check, state: dict) -> dict:
    result: dict = {"scenario": "complete", "errors": []}
    request, key = new_request(), f"saga-check-{uuid.uuid4()}"
    started = time.monotonic()
    answer = check.start(request, key)
    result["answer"] = answer.status
    expect(result, "answered 201 (or 202 while a step delay is set)", answer.status in (201, 202), answer)
    document = run_to_end(check, answer)
    result["seconds"] = round(time.monotonic() - started, 2)
    result["sagaId"] = document["sagaId"]
    expect(result, "saga COMPLETED", document["state"] == "COMPLETED", document["state"])
    expect(result, "every step SUCCEEDED",
           step_states(document) == {"record-decision": "SUCCEEDED", "queue-verdict-notification": "SUCCEEDED",
                                     "confirm-decision": "SUCCEEDED"}, step_states(document))
    actions = {(entry["step"], entry["action"]) for entry in document.get("log", [])}
    expect(result, "the log records each forward call",
           {("record-decision", "forward"), ("queue-verdict-notification", "forward"),
            ("confirm-decision", "forward")} <= actions, sorted(actions))

    decision = check.decision(document["decisionId"])
    expect(result, "the decision exists", decision.status == 200, decision)
    expect(result, "the decision is CONFIRMED",
           (decision.field("saga") or {}).get("state") == "CONFIRMED", decision.field("saga"))
    expect(result, "the decision knows its saga", (decision.field("saga") or {}).get("sagaId") == document["sagaId"])
    notification = check.notification(document["notificationId"])
    expect(result, "the VERDICT DM is queued for the applicant",
           notification.status == 200 and notification.field("type") == "VERDICT"
           and notification.field("recipientId") == APPLICANT_ID, notification)
    expect(result, "the DM carries the saga's id",
           (notification.field("metadata") or {}).get("sagaId") == document["sagaId"], notification.field("metadata"))
    state["completed"] = {"request": request, "key": key, "sagaId": document["sagaId"]}
    return result


def replay(check: Check, state: dict) -> dict:
    result: dict = {"scenario": "replay", "errors": []}
    if "completed" not in state:
        complete(check, state)
    first = state["completed"]
    answer = check.start(first["request"], first["key"])
    result["answer"] = answer.status
    expect(result, "same Idempotency-Key, same saga", answer.field("sagaId") == first["sagaId"], answer)
    expect(result, "a completed saga found again answers 200", answer.status == 200, answer.status)
    expect(result, "Idempotent-Replay: true", answer.headers.get("idempotent-replay") == "true", answer.headers)
    expect(result, "Location names the saga", answer.headers.get("location") == f"/sagas/{first['sagaId']}",
           answer.headers)
    expect(result, "still COMPLETED", answer.field("state") == "COMPLETED", answer.field("state"))
    decisions = check.session_decisions(first["request"]["sessionId"])
    expect(result, "one decision for the session", len(decisions) == 1, len(decisions))
    return result


def refused(check: Check, state: dict) -> dict:
    result: dict = {"scenario": "refused", "errors": []}
    request = new_request(UNKNOWN_APPLICANT_ID, UNKNOWN_CREDENTIAL_ID)
    answer = check.start(request)
    result["answer"] = answer.status
    expect(result, "moderation's 422 is passed on", answer.status == 422, answer)
    expect(result, "saga FAILED", answer.field("state") == "FAILED", answer.field("state"))
    expect(result, "error copied from moderation", bool(answer.field("error")) and bool(answer.field("message")), answer)
    if answer.field("sagaId"):
        document = check.saga(answer.field("sagaId")) or {}
        states = step_states(document)
        expect(result, "step 1 FAILED, nothing else attempted",
               states.get("record-decision") == "FAILED"
               and states.get("queue-verdict-notification") in ("PENDING", "SKIPPED")
               and states.get("confirm-decision") in ("PENDING", "SKIPPED"), states)
    expect(result, "no decision left behind", check.session_decisions(request["sessionId"]) == [])

    not_object = check.http("POST", f"{GATEWAY_URL}/sagas/decision-verdicts", raw_body="[1, 2]")
    expect(result, "a JSON array -> 400 VALIDATION_ERROR",
           not_object.status == 400 and not_object.field("error") == "VALIDATION_ERROR", not_object)
    expect(result, "and no saga", not not_object.field("sagaId"), not_object)
    return result


def compensation(check: Check, state: dict) -> dict:
    result: dict = {"scenario": "compensation", "errors": []}
    request = new_request()
    check.compose.run("stop", *DMS_SERVICES, timeout=90)
    try:
        answer = check.start(request, timeout=30)
        result["answer"] = answer.status
        saga_id = answer.field("sagaId")
        if not saga_id:
            raise RuntimeError(f"POST /sagas/decision-verdicts answered without a sagaId: {answer}")
        result["sagaId"] = saga_id
        expect(result, "answered 202 while compensating", answer.status == 202, answer)
        document = check.wait_until("saga COMPENSATING",
                                    lambda: (lambda s: s if s and s["state"] == "COMPENSATING" else None)(check.saga(saga_id)),
                                    timeout=60)
        # The DMS stays down a little longer: the compensation must keep trying, not give up.
        time.sleep(10)
        document = check.saga(saga_id) or document
        expect(result, "still COMPENSATING while the DMS is down", document["state"] == "COMPENSATING", document["state"])
        decision = check.decision(document["decisionId"]) if document.get("decisionId") else None
        expect(result, "the decision is still PENDING (cancel first, reverse order)",
               decision is not None and (decision.field("saga") or {}).get("state") == "PENDING", decision)
        if decision is not None and decision.status == 200:
            locked = check.http("PATCH", f"{GATEWAY_URL}/decisions/{document['decisionId']}", {"action": "FLAG"})
            expect(result, "semantic lock: PATCH -> 409 DECISION_PENDING",
                   locked.status == 409 and locked.field("error") == "DECISION_PENDING", locked)
    finally:
        check.compose.run("start", *DMS_SERVICES, timeout=120)
    restarted = time.monotonic()
    document = check.finished(saga_id, timeout=120)
    result["compensatedSecondsAfterRestart"] = round(time.monotonic() - restarted, 1)
    expect(result, "saga COMPENSATED", document["state"] == "COMPENSATED", document["state"])
    compensations = [entry["step"] for entry in document.get("log", [])
                     if entry["action"] == "compensate" and str(entry["outcome"]).startswith("2")]
    expect(result, "compensated in reverse order (notification, then decision)",
           compensations[:2] == ["queue-verdict-notification", "record-decision"], compensations)
    if document.get("decisionId"):
        gone = check.decision(document["decisionId"])
        expect(result, "the decision is voided (404)", gone.status == 404, gone)
    expect(result, "no decision left for the session", check.session_decisions(request["sessionId"]) == [])

    late_decision = check.http("POST", f"{MODERATION_URL}/internal/sagas/{saga_id}/decision", request)
    expect(result, "moderation refuses a late step 1: 409 SAGA_COMPENSATED",
           late_decision.status == 409 and late_decision.field("error") == "SAGA_COMPENSATED", late_decision)
    late_dm = check.http("POST", f"{DMS_URL}/internal/sagas/{saga_id}/notification",
                         {"decisionId": document.get("decisionId") or str(uuid.uuid4()), "applicantId": APPLICANT_ID,
                          "action": "ACCEPT", "violatedRules": [], "issuedAt": now_iso()})
    expect(result, "the DMS refuses a late step 2: 409 SAGA_COMPENSATED",
           late_dm.status == 409 and late_dm.field("error") == "SAGA_COMPENSATED", late_dm)
    return result


def recovery(check: Check, state: dict) -> dict:
    result: dict = {"scenario": "recovery", "errors": []}
    delay = float(check.env("gateway-service", "SAGA_STEP_DELAY_SECONDS") or 0)
    result["stepDelaySeconds"] = delay
    if delay < 3:
        result["skipped"] = "needs GATEWAY_SAGA_STEP_DELAY_SECONDS >= 3 on the Gateway"
        return result
    request, key = new_request(), f"saga-check-{uuid.uuid4()}"
    known = check.saga_ids()

    def post() -> None:
        # The POST is cut off when the Gateway is killed; its answer does not matter.
        try:
            check.start(request, key, timeout=30)
        except RuntimeError:
            pass

    threading.Thread(target=post, daemon=True).start()

    def between_steps(saga: dict | None) -> dict | None:
        # The step delay holds the saga before step 2 and again before step 3. The first wait is
        # the target: a kill that lands late still falls into the second. The second is the
        # fallback for a poll too slow to see the first.
        states = step_states(saga) if saga else {}
        if states.get("record-decision") != "SUCCEEDED":
            return None
        if states.get("queue-verdict-notification") in ("PENDING", "RUNNING"):
            return saga
        if states.get("queue-verdict-notification") == "SUCCEEDED" and states.get("confirm-decision") == "PENDING":
            return saga
        return None

    document = check.wait_until("step 1 done, step 3 not started",
                                lambda: between_steps(check.newest_saga(known)), timeout=30, interval=0.3)
    saga_id = document["sagaId"]
    result["sagaId"] = saga_id
    result["killedWith"] = step_states(document)
    check.compose.run("kill", "gateway-service")
    check.compose.run("start", "gateway-service", timeout=90)
    restarted = time.monotonic()
    document = check.finished(saga_id, timeout=120)
    result["completedSecondsAfterRestart"] = round(time.monotonic() - restarted, 1)
    expect(result, "saga COMPLETED after the restart", document["state"] == "COMPLETED", document["state"])
    expect(result, "the log shows it resumed",
           any(entry["action"] == "state" and entry["outcome"] == "RESUMED" for entry in document.get("log", [])),
           document.get("log"))
    expect(result, "one decision for the session", len(check.session_decisions(request["sessionId"])) == 1)
    decision = check.decision(document["decisionId"]) if document.get("decisionId") else None
    expect(result, "the decision is CONFIRMED",
           decision is not None and (decision.field("saga") or {}).get("state") == "CONFIRMED", decision)
    notification = check.notification(document["notificationId"]) if document.get("notificationId") else None
    expect(result, "the VERDICT DM is queued", notification is not None and notification.status == 200, notification)
    again = check.start(request, key)
    expect(result, "the Idempotency-Key still finds the saga", again.field("sagaId") == saga_id, again)
    return result


def api(check: Check, state: dict) -> dict:
    result: dict = {"scenario": "api", "errors": []}
    unknown = check.http("GET", f"{GATEWAY_URL}/sagas/{uuid.uuid4()}")
    expect(result, "unknown saga -> 404 SAGA_NOT_FOUND",
           unknown.status == 404 and unknown.field("error") == "SAGA_NOT_FOUND", unknown)
    malformed = check.http("GET", f"{GATEWAY_URL}/sagas/not-a-uuid")
    expect(result, "non-UUID -> 400 VALIDATION_ERROR",
           malformed.status == 400 and malformed.field("error") == "VALIDATION_ERROR", malformed)
    listing = check.http("GET", f"{GATEWAY_URL}/sagas?state=COMPLETED&limit=5")
    expect(result, "GET /sagas?state=COMPLETED lists completed sagas only",
           listing.status == 200 and all(s["state"] == "COMPLETED" for s in listing.body.get("sagas", [])), listing)
    bad_limit = check.http("GET", f"{GATEWAY_URL}/sagas?limit=0")
    expect(result, "limit outside 1..100 -> 400", bad_limit.status == 400, bad_limit)
    for path in (f"/internal/sagas/{uuid.uuid4()}/decision", f"/internal/sagas/{uuid.uuid4()}/notification"):
        routed = check.http("POST", f"{GATEWAY_URL}{path}", {})
        expect(result, f"{path.split('/')[-1]} participant route not routed: 404 ROUTE_NOT_FOUND",
               routed.status == 404 and routed.field("error") == "ROUTE_NOT_FOUND", routed)
    return result


SCENARIOS = {"complete": complete, "replay": replay, "refused": refused, "compensation": compensation,
             "recovery": recovery, "api": api}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="Compose project name (default: Compose's own default)")
    parser.add_argument("--env-file", help="passed to docker compose (only to resolve the Compose file)")
    parser.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")
    parser.add_argument("--evidence", type=Path, help="write the result as JSON here")
    args = parser.parse_args()
    check = Check(Compose(args.project, args.env_file))
    chosen = list(SCENARIOS) if args.scenario == "all" else [args.scenario]

    report: dict = {"timestamp": now_iso(), "scenarios": []}
    try:
        report["sagaEnabled"] = check.env("gateway-service", "SAGA_ENABLED") or "true"
        report["stepDelaySeconds"] = float(check.env("gateway-service", "SAGA_STEP_DELAY_SECONDS") or 0)
    except (RuntimeError, ValueError) as error:
        print(f"Cannot start: {error}")
        return 2
    if report["sagaEnabled"].lower() != "true":
        print("SAGA_ENABLED is not true on gateway-service")
        return 2

    state: dict = {}
    for name in chosen:
        try:
            outcome = SCENARIOS[name](check, state)
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError, IndexError,
                TypeError, AttributeError) as error:
            outcome = {"scenario": name, "errors": [f"{type(error).__name__}: {error}"]}
        report["scenarios"].append(outcome)
        status = "SKIPPED" if outcome.get("skipped") else ("OK" if not outcome["errors"] else "FAILED")
        print(f"{name}: {status} {json.dumps({k: v for k, v in outcome.items() if k != 'checks'})}")
    if args.evidence:
        args.evidence.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if all(not s["errors"] for s in report["scenarios"]) else 1


if __name__ == "__main__":
    sys.exit(main())
