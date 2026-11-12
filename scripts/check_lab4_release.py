"""Lab 4 release gate: the Message Broker in Compose and the services wired to it.

Builds on check_lab3_release.py (every application image pinned, nothing built locally, private
ports) and adds what Lab 4 needs: the message-broker image pinned and private, Player and Session
taking their events from it, and no REST stand-in or retired event mode left on. Uses .env.example
only; never prints a resolved Compose environment or loads local credentials.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("lab3_release", ROOT / "scripts" / "check_lab3_release.py")
lab3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lab3)

# Keep in sync with Compose when the broker publishes a release.
BROKER_IMAGE = "drateeva/message-broker:0.5.0"
BROKER_ADDRESS = "message-broker:9091"
SD_URL = "http://service-discovery:8089"


def images() -> dict[str, str]:
    return {**lab3.IMAGES, "message-broker": BROKER_IMAGE}


def _environment(entry: dict) -> dict:
    environment = entry.get("environment") or {}
    return {key: str(value) for key, value in environment.items()}


def validate_config(config: dict) -> list[str]:
    errors = lab3.validate_config(config)
    services = config.get("services", {})

    broker = services.get("message-broker")
    if broker is None:
        return errors + ["message-broker: missing from Compose"]
    if broker.get("image") != BROKER_IMAGE:
        errors.append(f"message-broker: expected {BROKER_IMAGE}")
    if "build" in broker:
        errors.append("message-broker: root Compose must use the published image, not a build context")
    if broker.get("ports"):
        errors.append("message-broker: HTTP 8091 and gRPC 9091 must stay private to the Compose network")
    if broker.get("deploy", {}).get("replicas", 1) != 1:
        errors.append("message-broker: one instance only (its topic queues are one SQLite file)")
    if not any(volume.get("type") == "volume" and volume.get("target") == "/data" for volume in broker.get("volumes") or []):
        errors.append("message-broker: a named volume must be mounted on /data (durable queues and dead letters)")
    if _environment(broker).get("DISCOVERY_URL") != SD_URL:
        errors.append(f"message-broker: DISCOVERY_URL must be {SD_URL}")

    player = _environment(services.get("player-service", {}))
    if player.get("MESSAGING_ENABLED") != "true":
        errors.append("player-service: MESSAGING_ENABLED must be true (events from the broker)")

    session = _environment(services.get("server-moderation-session-service", {}))
    if session.get("MESSAGING_ENABLED") != "true":
        errors.append("server-moderation-session-service: MESSAGING_ENABLED must be true (events from the broker)")
    if session.get("MESSAGING_BROKER_ADDRESS") != BROKER_ADDRESS:
        errors.append(f"server-moderation-session-service: MESSAGING_BROKER_ADDRESS must be {BROKER_ADDRESS}")
    if session.get("DMS_CLIENT_MODE") != "broker":
        errors.append("server-moderation-session-service: DMS_CLIENT_MODE must be broker (http was removed in Lab 4)")
    for mode in ("APPLICANT_CLIENT_MODE", "RULES_CLIENT_MODE"):
        if session.get(mode) not in {"http", "broker"}:
            errors.append(f"server-moderation-session-service: {mode} must be http or broker")

    for name, entry in services.items():
        if _environment(entry).get("MOCK_EVENTS_ENABLED", "false").lower() == "true":
            errors.append(f"{name}: MOCK_EVENTS_ENABLED must not be on in Compose (REST stand-ins are local only)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-published", action="store_true",
                        help="Fail unless every pinned public image, the broker's included, has both architectures and matching latest")
    args = parser.parse_args()
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(ROOT / ".env.example"), "-f", str(ROOT / "docker-compose.yml"),
         "config", "--format", "json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode:
        print("Compose validation failed; inspect docker compose with .env.example locally.", file=sys.stderr)
        return 1
    errors = validate_config(json.loads(result.stdout))
    if args.require_published:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            for image_errors in executor.map(lab3.validate_public_image, images().values()):
                errors.extend(image_errors)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f"All {len(images())} application images pinned; message-broker private and wired to Player and Session.")
    print("Public manifests and latest digests verified." if args.require_published
          else "Publication not checked; use --require-published before release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
