"""Validate the ten application image tags and optionally their public DockerHub manifests.

Uses .env.example only; never prints a resolved Compose environment or loads local credentials.
Each application has an explicit repository and version; patch releases need not move together.
Database/Redis images retain their own upstream versions.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
# Keep these pinned references in sync with Compose when each service publishes a release.
IMAGES = {
    "player-service": "drateeva/player-service:0.4.0",
    "server-moderation-session-service": "drateeva/server-moderation-session-service:0.4.0",
    "applicant-service": "caramisca/applicant-service:0.4.0",
    "credential-service": "caramisca/credential-service:0.4.0",
    "server-rules-service": "diana7376/server-rules-service:0.4.2",
    "university-record-service": "diana7376/university-record-service:0.4.2",
    "moderation-service": "andiblindu1/moderation-service:0.4.0",
    "discord-dms-service": "andiblindu1/discord-dms-service:0.4.0",
    "gateway-service": "diana7376/gateway-service:0.4.1",
    "service-discovery": "drateeva/service-discovery:0.4.0",
}


def validate_config(config: dict) -> list[str]:
    errors = []
    services = config.get("services", {})
    for service, expected in IMAGES.items():
        entry = services.get(service, {})
        if entry.get("image") != expected:
            errors.append(f"{service}: expected {expected}")
        if "build" in entry:
            errors.append(f"{service}: root Compose must use published images, not build contexts")
    if services.get("service-discovery", {}).get("ports"):
        errors.append("service-discovery: control-plane port must not be published")
    gateway_ports = services.get("gateway-service", {}).get("ports", [])
    if any(str(port.get("target")) == "8090" for port in gateway_ports):
        errors.append("gateway-service: internal port 8090 must not be published")
    for service in ("applicant-service", "credential-service"):
        entry = services.get(service, {})
        if entry.get("deploy", {}).get("replicas", 0) < 2:
            errors.append(f"{service}: at least two initial replicas required")
        environment = entry.get("environment", {})
        if environment.get("Storage__Provider") != "Redis" or environment.get("ServiceDiscovery__Url") != "http://service-discovery:8089":
            errors.append(f"{service}: replicas require shared Redis and explicit SD registration")
    return errors


def tag_metadata(repository: str, tag: str) -> dict:
    request = urllib.request.Request(
        f"https://hub.docker.com/v2/repositories/{repository}/tags/{tag}",
        headers={"User-Agent": "pad-team19-release-check"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def validate_public_image(reference: str) -> list[str]:
    try:
        repository, tag = reference.rsplit(":", 1)
        version, latest = tag_metadata(repository, tag), tag_metadata(repository, "latest")
        platforms = {(image.get("os"), image.get("architecture")) for image in version.get("images", [])}
        errors = []
        if not {("linux", "amd64"), ("linux", "arm64")} <= platforms:
            errors.append(f"{reference}: missing linux/amd64 or linux/arm64")
        if not version.get("digest") or version["digest"] != latest.get("digest"):
            errors.append(f"{repository}: latest digest does not match {tag}")
        return errors
    except urllib.error.HTTPError as error:
        return [f"{reference}: public DockerHub lookup returned HTTP {error.code}"]
    except (OSError, ValueError, KeyError):
        return [f"{reference}: could not verify public image metadata"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-published", action="store_true", help="Fail unless every pinned public image has both architectures and matching latest")
    args = parser.parse_args()
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(ROOT / ".env.example"), "-f", str(ROOT / "docker-compose.yml"), "config", "--format", "json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode:
        print("Compose validation failed; inspect docker compose with .env.example locally.", file=sys.stderr)
        return 1
    errors = validate_config(json.loads(result.stdout))
    if args.require_published:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            for image_errors in executor.map(validate_public_image, IMAGES.values()):
                errors.extend(image_errors)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f"All {len(IMAGES)} application images match their pinned per-service versions; database versions are independent.")
    print("Public manifests and latest digests verified." if args.require_published else "Publication not checked; use --require-published before release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
