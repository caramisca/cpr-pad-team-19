"""Exercise automatic Redis failover in a running, dedicated Compose demo project."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import subprocess
import time
import uuid


def check(compose: list[str], group: str) -> None:
    def run(*args: str, stdin: str | None = None) -> str:
        result = subprocess.run(compose + list(args), input=stdin, capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError(f"Compose command failed: {args[0]} {args[1]}")
        return result.stdout.strip()

    def wait_for(description, probe, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = probe()
                if result:
                    return result
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            time.sleep(1)
        raise RuntimeError(f"{group}: timed out waiting for {description}")

    members = {}
    for index in range(1, 4):
        member = f"{group}-redis-{index}"
        address = run("exec", "-T", member, "printenv", "REDIS_NODE_ADDRESS")
        members[address] = member

    def primary():
        address = run("exec", "-T", "redis-sentinel-1", "redis-cli", "--raw", "-p", "26379",
                      "SENTINEL", "get-master-addr-by-name", group).splitlines()
        if len(address) != 2 or address[0] not in members:
            raise RuntimeError(f"{group}: Sentinel returned an unexpected address")
        return members[address[0]]

    old_primary = primary()
    reader = next(f"{group}-redis-{i}" for i in range(1, 4) if f"{group}-redis-{i}" != old_primary)

    def redis(*args, stdin=None):
        return run("exec", "-T", reader, "redis-cli", "--raw", "-h", f"{group}-redis", *args, stdin=stdin)

    key = f"lab5:failover:{uuid.uuid4().hex}"
    seeded = redis(stdin=f"SET {key} before EX 180\nWAIT 2 5000\n")
    if seeded.splitlines() != ["OK", "2"]:
        raise RuntimeError(f"{group}: the demo value did not reach both replicas")
    started = time.monotonic()
    try:
        run("stop", "-t", "3", old_primary)

        def elected():
            candidate = primary()
            return candidate if candidate != old_primary else None

        new_primary = wait_for("new Sentinel primary", elected)
        wait_for("read through the existing host", lambda: redis("GET", key) == "before")
        wait_for("write through the existing host", lambda: redis("SET", key, "after", "EX", "180") == "OK")
        assert redis("GET", key) == "after"
        elapsed = time.monotonic() - started
    finally:
        run("start", old_primary)

    def rejoined():
        info = run("exec", "-T", old_primary, "redis-cli", "--raw", "INFO", "replication").splitlines()
        return "role:slave" in info and "master_link_status:up" in info

    wait_for("old primary to rejoin as a replica", rejoined)
    replica_value = run("exec", "-T", old_primary, "redis-cli", "--raw", "GET", key)
    if replica_value != "after":
        raise RuntimeError(f"{group}: restarted replica did not receive the post-failover write")
    print(f"{group}: {old_primary} -> {new_primary} in {elapsed:.1f}s; read/write through {group}-redis; old primary rejoined")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", default=".env.example")
    args = parser.parse_args()
    compose = ["docker", "compose", "--env-file", args.env_file, "-p", args.project]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda group: check(compose, group), ("applicant", "credential")))
