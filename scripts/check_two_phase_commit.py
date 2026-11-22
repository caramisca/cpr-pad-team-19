"""Check the two-phase commit that closes a shift (Lab 5, Grade 8) on a running Compose project.

POST /sessions/{id}/close changes server-moderation-session-service's database (the shift) and
player-service's (the shift credited to every moderator) as one transaction, coordinated by the
message-broker (contracts/two-phase.md, docs/LAB_5_TWO_PHASE_COMMIT.md). Five scenarios:

1. commit: both databases change together; the later session.closed doesn't count the shift twice;
2. no vote: a junior moderator who isn't a registered player -> 409 SHIFT_CLOSE_ABORTED, nothing
   changed in either database;
3. participant crash: every player-service instance killed after the decision, while its part is
   prepared -> the prepared transaction survives, the broker commits it once player-service is back;
4. coordinator crash: the broker killed after writing the decision, before phase 2 -> after its
   restart it finishes the commit from its log;
5. database failover: the primary of player-postgres killed while the transaction is prepared ->
   the new primary has it (synchronous replication) and the broker commits it there.

Scenarios 3-5 kill something between the decision and phase 2, so the broker must run with
BROKER_TWO_PHASE_PHASE_TWO_DELAY_SECONDS (e.g. 4): the coordinator then waits that long after the
decision. Standard library only; HTTP calls run inside the service-discovery container and SQL
inside the clusters' members (superuser password already in those containers), so no .env is read
and no secret printed. It creates players and shifts of its own.

    python3 scripts/check_two_phase_commit.py --project <name> --env-file <file> --evidence docs/evidence/lab5-two-phase-commit.json
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

SESSION_URL = "http://server-moderation-session-service:8082"
PLAYER_URL = "http://player-service:8081"
BROKER_URL = "http://message-broker:8091"
MEMBERS = 3
DATABASES = {"player": "playerdb", "session": "sessiondb"}

# One HTTP request from inside the Compose network; prints {"status", "body"} as JSON.
HTTP_SCRIPT = r"""
import json, sys, urllib.request, urllib.error
method, url, body, timeout = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
data = body.encode() if body else None
request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status, raw = response.status, response.read()
except urllib.error.HTTPError as error:
    status, raw = error.code, error.read()
except Exception as error:
    status, raw = 0, json.dumps({"error": "NO_ANSWER", "message": str(error)}).encode()
try:
    parsed = json.loads(raw) if raw else None
except ValueError:
    parsed = raw.decode(errors="replace")
print(json.dumps({"status": status, "body": parsed}))
"""


class Check:
    def __init__(self, project: str | None, env_file: str | None) -> None:
        self.base = ["docker", "compose"]
        if project:
            self.base += ["-p", project]
        if env_file:
            self.base += ["--env-file", env_file]

    def run(self, *args: str, check: bool = True, timeout: float = 60) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(self.base + list(args), capture_output=True, text=True, check=check, timeout=timeout)
        except subprocess.TimeoutExpired:
            if check:
                raise RuntimeError(f"docker compose {' '.join(args[:2])} took longer than {timeout} s")
            return subprocess.CompletedProcess(args, 124, "", f"timed out after {timeout} s")

    def http(self, method: str, url: str, body: dict | None = None, timeout: float = 15) -> tuple[int, object]:
        result = self.run("exec", "-T", "service-discovery", "python", "-c", HTTP_SCRIPT, method, url,
                          json.dumps(body) if body is not None else "", str(timeout), check=False, timeout=timeout + 15)
        if result.returncode != 0:
            raise RuntimeError(f"{method} {url}: {result.stderr.strip()}")
        answer = json.loads(result.stdout)
        return answer["status"], answer["body"]

    def members(self, cluster: str) -> list[dict]:
        for index in range(1, MEMBERS + 1):
            result = self.run("exec", "-T", f"{cluster}-postgres-{index}", "patronictl", "-c",
                              "/etc/patroni/patroni.yml", "list", "-f", "json", check=False)
            if result.returncode == 0:
                return json.loads(result.stdout)
        raise RuntimeError(f"no member of {cluster}-postgres answers patronictl")

    def leader(self, cluster: str) -> str | None:
        return next((m["Member"] for m in self.members(cluster)
                     if m.get("Role") == "Leader" and m.get("State") == "running"), None)

    def sql(self, cluster: str, query: str) -> list[str]:
        """Rows (tab-separated) of a query on the service's database, through its HAProxy (the primary)."""
        script = ('PGPASSWORD="$PATRONI_SUPERUSER_PASSWORD" PGCONNECT_TIMEOUT=3 psql -h ' + cluster + '-postgres '
                  '-U postgres -d ' + DATABASES[cluster] + ' -v ON_ERROR_STOP=1 -AtF "\t" -c "$0"')
        last_error = ""
        for _ in range(60):  # a failover makes the router refuse for ~20 s
            for index in range(1, MEMBERS + 1):
                result = self.run("exec", "-T", f"{cluster}-postgres-{index}", "sh", "-c", script, query,
                                  check=False, timeout=20)
                if result.returncode == 0:
                    return [line for line in result.stdout.splitlines() if line]
                last_error = result.stderr.strip()
            time.sleep(1)
        raise RuntimeError(f"{cluster}: {query}: {last_error}")

    # -- the system's own state -------------------------------------------------------------------

    def register(self) -> str:
        status, body = self.http("POST", f"{PLAYER_URL}/players",
                                 {"discordId": f"2pc-check-{uuid.uuid4()}", "displayName": "2PC check"})
        if status != 201:
            raise RuntimeError(f"POST /players answered {status} {body}")
        return body["id"]

    def open_shift(self, moderator: str, juniors: list[str]) -> str:
        status, body = self.http("POST", f"{SESSION_URL}/sessions", {"moderatorId": moderator, "juniorModeratorIds": juniors})
        if status != 201:
            raise RuntimeError(f"POST /sessions answered {status} {body}")
        return body["id"]

    def shifts(self, player: str) -> int:
        return int(self.sql("player", f"SELECT total_shifts FROM player_stats WHERE player_id = '{player}'")[0])

    def session_row(self, session: str) -> dict:
        status, closed_by = self.sql("session", "SELECT status, coalesce(close_transaction_id::text, '') "
                                                f"FROM sessions WHERE id = '{session}'")[0].split("\t")
        return {"status": status, "closeTransactionId": closed_by or None}

    def prepared(self, cluster: str) -> list[str]:
        return self.sql(cluster, "SELECT gid FROM pg_prepared_xacts ORDER BY prepared")

    def transaction(self, transaction_id: str) -> dict | None:
        status, body = self.http("GET", f"{BROKER_URL}/two-phase/transactions/{transaction_id}")
        return body if status == 200 else None

    def newest_transaction(self, since: str) -> dict | None:
        status, body = self.http("GET", f"{BROKER_URL}/two-phase/transactions?limit=5", timeout=5)
        if status != 200:
            return None
        return next((t for t in body["transactions"] if t["createdAt"] >= since), None)

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


def now_iso(offset_seconds: float = 0) -> str:
    moment = datetime.fromtimestamp(time.time() + offset_seconds, timezone.utc)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Background:
    """POST /sessions/{id}/close on a thread of its own, so the check can kill something meanwhile."""

    def __init__(self, check: Check, session: str) -> None:
        self.answer: tuple[int, object] | None = None
        self.started = time.monotonic()
        self.seconds: float | None = None
        self.thread = threading.Thread(target=self._close, args=(check, session), daemon=True)
        self.thread.start()

    def _close(self, check: Check, session: str) -> None:
        try:
            self.answer = check.http("POST", f"{SESSION_URL}/sessions/{session}/close", timeout=20)
        except RuntimeError as error:
            self.answer = (0, {"error": "NO_ANSWER", "message": str(error)})
        self.seconds = round(time.monotonic() - self.started, 2)

    def result(self) -> tuple[int, object]:
        self.thread.join(60)
        return self.answer or (0, None)


def decided(check: Check, since: str) -> dict:
    """Waits for the decision of the transaction started after ``since`` (phase 2 is delayed)."""
    return check.wait_until("the coordinator's decision",
                            lambda: (lambda t: t if t and t["state"] != "PREPARING" else None)(check.newest_transaction(since)),
                            timeout=15, interval=0.2)


def expect(result: dict, name: str, condition: bool, detail: object = None) -> None:
    result.setdefault("checks", {})[name] = bool(condition)
    if not condition:
        result["errors"].append(f"{name}" + (f": {detail}" if detail is not None else ""))


# -- scenarios ---------------------------------------------------------------------------------------

def commit(check: Check) -> dict:
    result: dict = {"scenario": "commit", "errors": []}
    moderator, junior = check.register(), check.register()
    session = check.open_shift(moderator, [junior])
    started = time.monotonic()
    status, body = check.http("POST", f"{SESSION_URL}/sessions/{session}/close", timeout=20)
    result["closeStatus"], result["closeSeconds"] = status, round(time.monotonic() - started, 2)
    expect(result, "close answered 200 CLOSED", status == 200 and body.get("status") == "CLOSED", body)
    row = check.session_row(session)
    transaction_id = row["closeTransactionId"]
    result["transactionId"] = transaction_id
    expect(result, "session closed by the transaction", row["status"] == "CLOSED" and transaction_id, row)
    done = check.wait_until("phase 2 acknowledged", lambda: (lambda t: t if t and t["completed"] else None)(
        check.transaction(transaction_id)), timeout=30)
    result["coordinator"] = done
    expect(result, "coordinator COMMITTED and completed", done["state"] == "COMMITTED")
    time.sleep(5)  # session.closed (eventId = the transaction) reaches player-service meanwhile
    result["shifts"] = {"moderator": check.shifts(moderator), "junior": check.shifts(junior)}
    expect(result, "shift credited once to both players", result["shifts"] == {"moderator": 1, "junior": 1}, result["shifts"])
    processed = check.sql("player", f"SELECT event_type FROM processed_events WHERE event_id = '{transaction_id}'")
    expect(result, "player recorded the transaction as session.closed", processed == ["session.closed"], processed)
    result["preparedLeft"] = {"player": check.prepared("player"), "session": check.prepared("session")}
    expect(result, "no prepared transaction left", not any(result["preparedLeft"].values()), result["preparedLeft"])
    return result


def no_vote(check: Check) -> dict:
    result: dict = {"scenario": "no-vote", "errors": []}
    moderator = check.register()
    unknown = str(uuid.uuid4())
    session = check.open_shift(moderator, [unknown])
    since = now_iso(-1)
    status, body = check.http("POST", f"{SESSION_URL}/sessions/{session}/close", timeout=20)
    result["closeStatus"], result["closeBody"] = status, body
    expect(result, "close answered 409 SHIFT_CLOSE_ABORTED", status == 409 and body.get("error") == "SHIFT_CLOSE_ABORTED", body)
    row = check.session_row(session)
    expect(result, "session still open", row == {"status": "OPEN", "closeTransactionId": None}, row)
    expect(result, "moderator not credited", check.shifts(moderator) == 0)
    transaction = check.newest_transaction(since)
    result["coordinator"] = transaction
    expect(result, "coordinator ABORTED on player-service's NO",
           transaction and transaction["state"] == "ABORTED" and "not registered players" in (transaction["reason"] or ""))
    result["preparedLeft"] = {"player": check.prepared("player"), "session": check.prepared("session")}
    expect(result, "no prepared transaction left", not any(result["preparedLeft"].values()), result["preparedLeft"])
    return result


def participant_crash(check: Check) -> dict:
    result: dict = {"scenario": "participant-crash", "errors": []}
    moderator = check.register()
    session = check.open_shift(moderator, [])
    since = now_iso(-1)
    closing = Background(check, session)
    transaction = decided(check, since)
    transaction_id = transaction["transactionId"]
    result["transactionId"], result["decision"] = transaction_id, transaction["state"]
    check.run("kill", "player-service")
    result["killed"] = "player-service (every replica), after the decision, before phase 2"
    status, body = closing.result()
    result["closeStatus"], result["closeSeconds"] = status, closing.seconds
    expect(result, "close answered 200 (session committed its part)", status == 200, body)
    gid = f"player-service:{transaction_id}"
    expect(result, "player's part still prepared after the crash", gid in check.prepared("player"))
    expect(result, "moderator not credited yet", check.shifts(moderator) == 0)
    check.run("start", "player-service")
    restarted = time.monotonic()
    done = check.wait_until("the broker's commit to the restarted player-service", lambda: (
        lambda t: t if t and t["completed"] else None)(check.transaction(transaction_id)), timeout=120, interval=2)
    result["completedAfterRestartSeconds"] = round(time.monotonic() - restarted, 1)
    result["coordinator"] = done
    expect(result, "moderator credited once", check.shifts(moderator) == 1)
    expect(result, "no prepared transaction left", not check.prepared("player"))
    return result


def coordinator_crash(check: Check) -> dict:
    result: dict = {"scenario": "coordinator-crash", "errors": []}
    moderator = check.register()
    session = check.open_shift(moderator, [])
    since = now_iso(-1)
    closing = Background(check, session)
    transaction = decided(check, since)
    transaction_id = transaction["transactionId"]
    result["transactionId"], result["decision"] = transaction_id, transaction["state"]
    check.run("kill", "message-broker")
    result["killed"] = "message-broker, after writing the decision, before phase 2"
    status, body = closing.result()
    result["closeStatus"], result["closeBody"] = status, body
    expect(result, "close answered 503 DEPENDENCY_UNAVAILABLE (no decision reached session)",
           status == 503 and isinstance(body, dict) and body.get("error") == "DEPENDENCY_UNAVAILABLE", body)
    held = {"player": check.prepared("player"), "session": check.prepared("session")}
    result["preparedWhileBrokerDown"] = held
    expect(result, "both parts prepared while the broker is down",
           f"player-service:{transaction_id}" in held["player"]
           and f"server-moderation-session-service:{transaction_id}" in held["session"], held)
    expect(result, "session still open meanwhile", check.session_row(session)["status"] == "OPEN")
    check.run("start", "message-broker")
    restarted = time.monotonic()
    done = check.wait_until("recovery from the broker's log", lambda: (
        lambda t: t if t and t["completed"] else None)(check.transaction(transaction_id)), timeout=90, interval=2)
    result["completedAfterRestartSeconds"] = round(time.monotonic() - restarted, 1)
    result["coordinator"] = done
    expect(result, "recovered as COMMITTED", done["state"] == "COMMITTED")
    row = check.session_row(session)
    expect(result, "session closed by the transaction", row == {"status": "CLOSED", "closeTransactionId": transaction_id}, row)
    time.sleep(5)
    expect(result, "moderator credited once", check.shifts(moderator) == 1)
    expect(result, "no prepared transaction left", not check.prepared("player") and not check.prepared("session"))
    return result


def database_failover(check: Check) -> dict:
    result: dict = {"scenario": "database-failover", "errors": []}
    moderator = check.register()
    session = check.open_shift(moderator, [])
    since = now_iso(-1)
    closing = Background(check, session)
    transaction = decided(check, since)
    transaction_id = transaction["transactionId"]
    primary = check.leader("player")
    check.run("kill", primary)
    killed = time.monotonic()
    result["transactionId"], result["primaryKilled"] = transaction_id, primary
    status, body = closing.result()
    result["closeStatus"] = status
    expect(result, "close answered 200 (session committed its part)", status == 200, body)
    done = check.wait_until("the commit on the new primary", lambda: (
        lambda t: t if t and t["completed"] else None)(check.transaction(transaction_id)), timeout=150, interval=2)
    result["completedAfterKillSeconds"] = round(time.monotonic() - killed, 1)
    result["coordinator"] = done
    result["primaryAfter"] = check.leader("player")
    expect(result, "another member is the primary", result["primaryAfter"] not in (None, primary), result["primaryAfter"])
    expect(result, "moderator credited once on the new primary", check.shifts(moderator) == 1)
    expect(result, "no prepared transaction left", not check.prepared("player"))
    check.run("start", primary)
    try:
        check.wait_until(f"{primary} back as a standby", lambda: any(
            m["Member"] == primary and m.get("State") == "streaming" for m in check.members("player")), timeout=120, interval=2)
        result["oldPrimaryRejoined"] = True
    except RuntimeError as error:
        result["errors"].append(str(error))
    return result


SCENARIOS = {"commit": commit, "no-vote": no_vote, "participant-crash": participant_crash,
             "coordinator-crash": coordinator_crash, "database-failover": database_failover}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="Compose project name (default: Compose's own default)")
    parser.add_argument("--env-file", help="passed to docker compose (only to resolve the Compose file)")
    parser.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")
    parser.add_argument("--evidence", type=Path, help="write the result as JSON here")
    args = parser.parse_args()
    check = Check(args.project, args.env_file)
    chosen = list(SCENARIOS) if args.scenario == "all" else [args.scenario]

    report: dict = {"timestamp": now_iso(), "scenarios": []}
    try:
        report["maxPreparedTransactions"] = {c: int(check.sql(c, "SHOW max_prepared_transactions")[0]) for c in DATABASES}
        delay = check.run("exec", "-T", "message-broker", "printenv", "TWO_PHASE_PHASE_TWO_DELAY_SECONDS", check=False)
        report["phaseTwoDelaySeconds"] = float(delay.stdout.strip() or 0)
    except (RuntimeError, ValueError) as error:
        print(f"Cannot start: {error}")
        return 2
    if not all(report["maxPreparedTransactions"].values()):
        print("max_prepared_transactions is 0: see docs/LAB_5_TWO_PHASE_COMMIT.md, 'Existing clusters'")
        return 2
    if report["phaseTwoDelaySeconds"] <= 0 and set(chosen) - {"commit", "no-vote"}:
        print("The crash scenarios need BROKER_TWO_PHASE_PHASE_TWO_DELAY_SECONDS (e.g. 4) on the broker")
        return 2

    for name in chosen:
        try:
            outcome = SCENARIOS[name](check)
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError, IndexError) as error:
            outcome = {"scenario": name, "errors": [f"{type(error).__name__}: {error}"]}
        report["scenarios"].append(outcome)
        print(f"{name}: {'OK' if not outcome['errors'] else 'FAILED'} "
              f"{json.dumps({k: v for k, v in outcome.items() if k not in ('coordinator', 'checks')})}")
    if args.evidence:
        args.evidence.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if all(not s["errors"] for s in report["scenarios"]) else 1


if __name__ == "__main__":
    sys.exit(main())
