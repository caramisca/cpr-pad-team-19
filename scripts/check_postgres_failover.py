"""Crash the primary of a replicated PostgreSQL cluster and check the failover (Lab 5, Grade 5).

For player-postgres and/or session-postgres (docs/LAB_5_DATABASE_FAILOVER.md), against a running
Compose project:

1. finds the cluster's primary (patronictl) and writes a marker row through the cluster's stable
   hostname (the HAProxy every service connects to);
2. kills the primary's container (SIGKILL, like a crash);
3. writes through the same hostname every 0.5 s until a write succeeds again, and reports how long
   writes were refused;
4. checks the marker is still there (no committed transaction lost: synchronous replication) and
   that another member is the primary now;
5. starts the old primary again and waits until it streams from the new one as a standby.

Standard library only. It runs psql inside the cluster's containers with the superuser password
those containers already have, so it reads no .env and prints no secret. The marker table is
public.failover_probe in the "postgres" maintenance database, never in the service's database.

    python3 scripts/check_postgres_failover.py --cluster player
    python3 scripts/check_postgres_failover.py --project <name> --cluster both --evidence docs/evidence/lab5-postgres-failover.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

MEMBERS = 3
WRITE_TIMEOUT_SECONDS = 60
REJOIN_TIMEOUT_SECONDS = 120


class Compose:
    def __init__(self, project: str | None, env_file: str | None) -> None:
        self.base = ["docker", "compose"]
        if project:
            self.base += ["-p", project]
        if env_file:
            self.base += ["--env-file", env_file]

    def run(self, *args: str, check: bool = True, timeout: float = 60) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(self.base + list(args), capture_output=True, text=True, check=check,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            if check:
                raise RuntimeError(f"docker compose {' '.join(args[:2])} took longer than {timeout} s")
            return subprocess.CompletedProcess(args, 124, "", f"timed out after {timeout} s")

    def members(self, cluster: str) -> list[dict]:
        """The cluster's members as patronictl reports them, asked of any member still running."""
        for index in range(1, MEMBERS + 1):
            result = self.run("exec", "-T", f"{cluster}-postgres-{index}", "patronictl",
                              "-c", "/etc/patroni/patroni.yml", "list", "-f", "json", check=False)
            if result.returncode == 0:
                return json.loads(result.stdout)
        raise RuntimeError(f"no member of {cluster}-postgres answers patronictl")

    def sql_via_router(self, cluster: str, member: str, sql: str) -> subprocess.CompletedProcess[str]:
        """Runs SQL through the cluster's stable hostname (HAProxy), from inside one of its members."""
        # A connection attempt gives up after 3 s and a statement after 5 s, so one attempt can't hang.
        script = ('PGPASSWORD="$PATRONI_SUPERUSER_PASSWORD" PGCONNECT_TIMEOUT=3 '
                  'PGOPTIONS="-c statement_timeout=5000" psql -h ' + cluster + '-postgres -U postgres '
                  '-d postgres -v ON_ERROR_STOP=1 -Atc "$0"')
        return self.run("exec", "-T", member, "sh", "-c", script, sql, check=False, timeout=15)


def leader_of(members: list[dict]) -> str | None:
    return next((m["Member"] for m in members if m.get("Role") == "Leader" and m.get("State") == "running"), None)


def check_cluster(compose: Compose, cluster: str) -> dict:
    result: dict = {"cluster": f"{cluster}-postgres", "errors": []}
    members = compose.members(cluster)
    old_leader = leader_of(members)
    if old_leader is None:
        result["errors"].append("no running primary before the test")
        return result
    survivor = next(m["Member"] for m in members if m["Member"] != old_leader)
    result["primaryBefore"] = old_leader
    result["membersBefore"] = [{k: m.get(k) for k in ("Member", "Role", "State", "Lag in MB")} for m in members]

    marker = f"before-crash-{datetime.now(timezone.utc).isoformat()}"
    setup = compose.sql_via_router(cluster, survivor,
        "CREATE TABLE IF NOT EXISTS failover_probe (id bigserial PRIMARY KEY, note text NOT NULL, "
        f"written_at timestamptz NOT NULL DEFAULT now()); INSERT INTO failover_probe (note) VALUES ('{marker}')")
    if setup.returncode != 0:
        result["errors"].append(f"could not write the marker: {setup.stderr.strip()}")
        return result

    compose.run("kill", old_leader)
    killed_at = time.monotonic()
    refused = 0
    while True:
        write = compose.sql_via_router(cluster, survivor,
            "INSERT INTO failover_probe (note) VALUES ('after-crash') RETURNING inet_server_addr()")
        if write.returncode == 0:
            break
        refused += 1
        if time.monotonic() - killed_at > WRITE_TIMEOUT_SECONDS:
            result["errors"].append(f"writes still refused {WRITE_TIMEOUT_SECONDS} s after the crash")
            return result
        time.sleep(0.5)
    result["writesRefusedForSeconds"] = round(time.monotonic() - killed_at, 1)
    result["refusedAttempts"] = refused

    found = compose.sql_via_router(cluster, survivor, f"SELECT count(*) FROM failover_probe WHERE note = '{marker}'")
    result["markerKept"] = found.returncode == 0 and found.stdout.strip() == "1"
    if not result["markerKept"]:
        result["errors"].append("the row committed before the crash is missing after the failover")
    new_leader = leader_of(compose.members(cluster))
    result["primaryAfter"] = new_leader
    if new_leader in (None, old_leader):
        result["errors"].append(f"expected a new primary, patronictl reports {new_leader}")

    compose.run("start", old_leader)
    started_at = time.monotonic()
    while time.monotonic() - started_at < REJOIN_TIMEOUT_SECONDS:
        members = compose.members(cluster)
        old = next((m for m in members if m["Member"] == old_leader), {})
        if old.get("Role") in ("Replica", "Sync Standby") and old.get("State") == "streaming":
            result["oldPrimaryRejoinedAs"] = old["Role"]
            result["rejoinSeconds"] = round(time.monotonic() - started_at, 1)
            break
        time.sleep(1)
    else:
        result["errors"].append(f"{old_leader} did not stream as a standby within {REJOIN_TIMEOUT_SECONDS} s")
    result["membersAfter"] = [{k: m.get(k) for k in ("Member", "Role", "State", "Lag in MB")}
                              for m in compose.members(cluster)]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cluster", choices=("player", "session", "both"), default="both")
    parser.add_argument("--project", help="Compose project name (default: Compose's own default)")
    parser.add_argument("--env-file", help="passed to docker compose (only to resolve the Compose file)")
    parser.add_argument("--evidence", type=Path, help="write the result as JSON here")
    args = parser.parse_args()
    compose = Compose(args.project, args.env_file)
    clusters = ("player", "session") if args.cluster == "both" else (args.cluster,)
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "clusters": []}
    for cluster in clusters:
        try:
            outcome = check_cluster(compose, cluster)
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            outcome = {"cluster": f"{cluster}-postgres", "errors": [str(error)]}
        report["clusters"].append(outcome)
        status = "OK" if not outcome["errors"] else "FAILED"
        print(f"{outcome['cluster']}: {status} {json.dumps({k: v for k, v in outcome.items() if not k.startswith('members')})}")
    if args.evidence:
        args.evidence.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if all(not c["errors"] for c in report["clusters"]) else 1


if __name__ == "__main__":
    sys.exit(main())
