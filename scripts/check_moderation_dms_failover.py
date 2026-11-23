"""Crash the primary of moderation-postgres and/or dms-redis and check the failover (Lab 5, Grade 5).

moderation-postgres is a Patroni cluster like player-postgres, so it is checked by the same procedure
as scripts/check_postgres_failover.py (imported, not copied): marker row, SIGKILL of the primary,
writes through the HAProxy until one succeeds, marker kept, old primary back as a standby.

dms-redis (docs/LAB_5_MODERATION_DMS_FAILOVER.md), against a running Compose project:

1. asks a Sentinel which member is the primary, and writes a marker key through the stable hostname
   dms-redis (the HAProxy), waiting until both replicas acknowledged it (WAIT: Redis replicates
   asynchronously, so only an acknowledged write is guaranteed to survive the crash);
2. kills the primary's container (SIGKILL, like a crash);
3. writes through dms-redis every 0.5 s until a write succeeds again, and reports how long writes
   were refused;
4. checks the marker is still there and that the Sentinels name another member the primary;
5. starts the old primary again and waits until it is a replica of the new one, in sync.

With --gateway-url, a second thread meanwhile reads through the Gateway every 0.5 s from the service
that owns the store (moderation: GET /decisions/<unknown id>; DMS: GET /notifications/<unknown id>)
and counts the answers: 404 means the service reached its store, 503 that it reported the outage, as
it should; a 500, another status or a request that hangs is an error. The API key is read from the
environment variable named by --api-key-env (default GATEWAY_API_KEY) and never printed.

Standard library only. The Redis commands run inside the Sentinel containers with the password those
containers already have, so the script reads no .env and prints no secret. The marker keys are named
failover-probe:* (outside discord-dms-service's key prefix) and deleted at the end.

    python3 scripts/check_moderation_dms_failover.py --store dms-redis
    python3 scripts/check_moderation_dms_failover.py --store both --gateway-url http://localhost:8080 --evidence docs/evidence/lab5-moderation-dms-failover.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_postgres_failover import Compose, check_cluster  # noqa: E402  (Daria's Grade 5 check)

MEMBERS = 3
MASTER_NAME = "dms-redis"
WRITE_TIMEOUT_SECONDS = 90
REJOIN_TIMEOUT_SECONDS = 120
PROBE_TIMEOUT_SECONDS = 10
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"
PROBE_PATHS = {"moderation-postgres": f"/decisions/{UNKNOWN_ID}", "dms-redis": f"/notifications/{UNKNOWN_ID}"}


class Redis:
    """Runs redis-cli inside the Sentinel containers (they have the password, as REDISCLI_AUTH)."""

    def __init__(self, compose: Compose) -> None:
        self.compose = compose

    def sentinel(self, *args: str) -> list[str]:
        for index in range(1, MEMBERS + 1):
            result = self.compose.run("exec", "-T", f"dms-redis-sentinel-{index}", "redis-cli", "-p", "26379",
                                      "SENTINEL", *args, check=False, timeout=15)
            if result.returncode == 0 and result.stdout.strip() and "ERR" not in result.stdout:
                return result.stdout.split()
        raise RuntimeError("no Sentinel of dms-redis answers")

    def primary(self) -> str:
        return self.sentinel("get-master-addr-by-name", MASTER_NAME)[0]

    def via_router(self, commands: str) -> subprocess.CompletedProcess[str]:
        """Sends the commands (one per line) over one connection to dms-redis, the HAProxy."""
        # One attempt gives up after 5 s, so it can't hang while no member is the primary.
        script = 'printf "%s\\n" "$0" | timeout 5 redis-cli -h dms-redis -p 6379'
        for index in range(1, MEMBERS + 1):
            result = self.compose.run("exec", "-T", f"dms-redis-sentinel-{index}", "sh", "-c", script, commands,
                                      check=False, timeout=15)
            # docker compose exec itself fails (not redis-cli) only when that container is not running.
            if "not running" not in result.stderr:
                return result
        raise RuntimeError("no Sentinel container is running")

    def replication(self, member: str) -> dict[str, str]:
        result = self.compose.run("exec", "-T", member, "redis-cli", "INFO", "replication", check=False, timeout=15)
        fields = {}
        for line in result.stdout.splitlines():
            key, _, value = line.strip().partition(":")
            if value:
                fields[key] = value
        return fields


def check_redis(compose: Compose) -> dict:
    result: dict = {"store": "dms-redis", "errors": []}
    redis = Redis(compose)
    old_primary = redis.primary()
    result["primaryBefore"] = old_primary
    result["replicasBefore"] = redis.replication(old_primary).get("connected_slaves")

    marker = f"failover-probe:{datetime.now(timezone.utc).isoformat()}"
    setup = redis.via_router(f"SET {marker} before-crash\nWAIT 2 3000")
    lines = setup.stdout.split()
    if not lines or lines[0] != "OK":
        result["errors"].append(f"could not write the marker: {(setup.stdout + setup.stderr).strip()}")
        return result
    result["markerAcknowledgedByReplicas"] = int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else None
    if result["markerAcknowledgedByReplicas"] == 0:
        result["errors"].append("no replica acknowledged the marker before the crash")

    compose.run("kill", old_primary)
    killed_at = time.monotonic()
    refused = 0
    while True:
        write = redis.via_router("SET failover-probe:after-crash after-crash")
        if write.stdout.strip() == "OK":
            break
        refused += 1
        if time.monotonic() - killed_at > WRITE_TIMEOUT_SECONDS:
            result["errors"].append(f"writes still refused {WRITE_TIMEOUT_SECONDS} s after the crash")
            return result
        time.sleep(0.5)
    result["writesRefusedForSeconds"] = round(time.monotonic() - killed_at, 1)
    result["refusedAttempts"] = refused

    found = redis.via_router(f"GET {marker}")
    result["markerKept"] = found.stdout.strip() == "before-crash"
    if not result["markerKept"]:
        result["errors"].append("the acknowledged marker is missing after the failover")
    new_primary = redis.primary()
    result["primaryAfter"] = new_primary
    if new_primary == old_primary:
        result["errors"].append(f"expected a new primary, the Sentinels still name {old_primary}")

    compose.run("start", old_primary)
    started_at = time.monotonic()
    while time.monotonic() - started_at < REJOIN_TIMEOUT_SECONDS:
        info = redis.replication(old_primary)
        if (info.get("role") == "slave" and info.get("master_host") == new_primary
                and info.get("master_link_status") == "up"):
            result["oldPrimaryRejoinedAs"] = f"replica of {new_primary}"
            result["rejoinSeconds"] = round(time.monotonic() - started_at, 1)
            break
        time.sleep(1)
    else:
        result["errors"].append(f"{old_primary} did not become an in-sync replica within {REJOIN_TIMEOUT_SECONDS} s")
    result["replicasAfter"] = redis.replication(new_primary).get("connected_slaves")
    # SENTINEL MASTER answers field, value, field, value, ...
    fields = redis.sentinel("master", MASTER_NAME)
    view = dict(zip(fields[0::2], fields[1::2]))
    result["sentinelsAfter"] = int(view.get("num-other-sentinels", "-1")) + 1
    result["quorum"] = view.get("quorum")
    redis.via_router(f"DEL {marker} failover-probe:after-crash")
    return result


class ServiceProbe(threading.Thread):
    """Reads through the Gateway every 0.5 s and counts the answers, until stopped."""

    def __init__(self, gateway_url: str, api_key: str, path: str) -> None:
        super().__init__(daemon=True)
        self.url = gateway_url.rstrip("/") + path
        self.api_key = api_key
        self.counts: dict[str, int] = {}
        self.slowest = 0.0
        self.stopping = threading.Event()

    def run(self) -> None:
        while not self.stopping.is_set():
            started = time.monotonic()
            request = urllib.request.Request(self.url, headers={"Authorization": f"Bearer {self.api_key}"})
            try:
                with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
                    outcome = str(response.status)
            except urllib.error.HTTPError as error:
                outcome = str(error.code)
                if error.code == 503:
                    try:
                        code = json.loads(error.read().decode("utf-8", "replace")).get("error", "?")
                    except (ValueError, AttributeError):
                        code = "?"
                    outcome += f" {code}"
                    outcome += " Retry-After" if error.headers.get("Retry-After") else " no Retry-After"
            except (urllib.error.URLError, TimeoutError, OSError):
                outcome = "no answer"
            self.slowest = max(self.slowest, time.monotonic() - started)
            self.counts[outcome] = self.counts.get(outcome, 0) + 1
            self.stopping.wait(0.5)

    def report(self) -> tuple[dict, list[str]]:
        errors = []
        for outcome, count in self.counts.items():
            if outcome != "404" and not outcome.startswith("503 "):
                errors.append(f"the service answered {outcome} {count} times during the failover")
            elif outcome.startswith("503 ") and outcome.endswith("no Retry-After"):
                errors.append(f"{count} answers 503 without Retry-After")
        if self.slowest >= PROBE_TIMEOUT_SECONDS:
            errors.append(f"a request through the Gateway took {self.slowest:.1f} s")
        return {"answers": self.counts, "slowestSeconds": round(self.slowest, 1)}, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", choices=("moderation-postgres", "dms-redis", "both"), default="both")
    parser.add_argument("--project", help="Compose project name (default: Compose's own default)")
    parser.add_argument("--env-file", help="passed to docker compose (only to resolve the Compose file)")
    parser.add_argument("--gateway-url", help="also read through the Gateway during the failover, e.g. http://localhost:8080")
    parser.add_argument("--api-key-env", default="GATEWAY_API_KEY",
                        help="environment variable holding a Gateway API key (with --gateway-url)")
    parser.add_argument("--evidence", type=Path, help="write the result as JSON here")
    args = parser.parse_args()
    api_key = os.environ.get(args.api_key_env, "") if args.gateway_url else ""
    if args.gateway_url and not api_key:
        parser.error(f"--gateway-url needs an API key in the environment variable {args.api_key_env}")

    compose = Compose(args.project, args.env_file)
    stores = ("moderation-postgres", "dms-redis") if args.store == "both" else (args.store,)
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "stores": []}
    for store in stores:
        probe = ServiceProbe(args.gateway_url, api_key, PROBE_PATHS[store]) if args.gateway_url else None
        if probe:
            probe.start()
        try:
            if store == "moderation-postgres":
                outcome = check_cluster(compose, "moderation")
                outcome = {"store": outcome.pop("cluster"), **outcome}
            else:
                outcome = check_redis(compose)
        except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, ValueError, IndexError) as error:
            outcome = {"store": store, "errors": [str(error)]}
        if probe:
            probe.stopping.set()
            probe.join()
            outcome["serviceProbe"], probe_errors = probe.report()
            outcome["errors"] += probe_errors
        report["stores"].append(outcome)
        status = "OK" if not outcome["errors"] else "FAILED"
        summary = {k: v for k, v in outcome.items() if not k.startswith("members")}
        print(f"{outcome['store']}: {status} {json.dumps(summary)}")
    if args.evidence:
        args.evidence.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if all(not s["errors"] for s in report["stores"]) else 1


if __name__ == "__main__":
    sys.exit(main())
