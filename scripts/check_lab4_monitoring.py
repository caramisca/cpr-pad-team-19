"""Verify actual Prometheus targets; scoped success is not full-team readiness.

Uses only the standard library. No .env or credentials are read. DNS jobs that
resolve no instances must fail readiness even though they produce no `up == 0`.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.error
import urllib.request

OWNED = {"prometheus": 1, "message-broker": 1, "applicant-service": 2, "credential-service": 2}
TEAM = {**OWNED, **dict.fromkeys(("player-service", "server-moderation-session-service",
    "server-rules-service", "university-record-service", "moderation-service", "discord-dms-service"), 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--scope", choices=("owned", "team"), default="team")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    required = OWNED if args.scope == "owned" else TEAM
    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "scope": args.scope,
              "required": required, "targets": [], "errors": []}
    try:
        # Private monitoring endpoints must be contacted directly, not via a public proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(args.prometheus_url.rstrip("/") + "/api/v1/targets", timeout=10) as response:
            data = json.load(response)
        if data.get("status") != "success":
            raise ValueError("Prometheus API did not return success")
        result["targets"] = [{"job": t["labels"].get("job"), "instance": t["labels"].get("instance"),
            "url": t["scrapeUrl"], "health": t["health"]} for t in data["data"]["activeTargets"]]
        for job, minimum in required.items():
            targets = [t for t in result["targets"] if t["job"] == job]
            healthy = {t["url"] for t in targets if t["health"] == "up"}
            if len(healthy) < minimum:
                result["errors"].append(f"{job}: {len(healthy)} distinct UP targets, expected at least {minimum}")
            if any(t["health"] != "up" for t in targets):
                result["errors"].append(f"{job}: at least one discovered target is not UP")
    except (OSError, ValueError, KeyError) as error:
        result["errors"].append(f"Monitoring verification failed: {type(error).__name__}")
    result["passed"] = not result["errors"]
    output = json.dumps(result, indent=2) + "\n"
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
