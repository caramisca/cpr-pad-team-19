"""Exercise Mihai's Lab 3 images in a fresh, isolated Compose project.

Requires locally available 0.4.0 images (reviewed/published images or explicitly built PR images).
The university registry is mocked inside Credential; this is not a full-team E2E test.
Only resources of the unique project created by this run are removed afterwards.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
KEY = "lab3-smoke-fixture-key-not-a-production-secret"


def command(args: list[str], **kwargs) -> str:
    return subprocess.check_output(args, text=True, **kwargs).strip()


def wait_for(check, description: str, seconds: float = 45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(0.5)
    raise AssertionError(f"Timed out: {description}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    project = "pad-lab3-smoke-" + uuid.uuid4().hex[:8]
    directory = Path(tempfile.mkdtemp(prefix=project + "-"))
    path = directory / "compose.json"
    config = json.loads(command(["docker", "compose", "--env-file", str(ROOT / ".env.example"), "-f", str(ROOT / "docker-compose.yml"), "config", "--format", "json"]))
    selected = {"service-discovery", "gateway-service", "applicant-service", "credential-service", "applicant-redis", "credential-redis", "applicant-seed", "credential-seed"}
    config["services"] = {name: value for name, value in config["services"].items() if name in selected}
    config.pop("name", None)
    config["networks"] = {"default": {}}
    for value in config["services"].values():
        value["pull_policy"] = "never"
        value["depends_on"] = {name: settings for name, settings in value.get("depends_on", {}).items() if name in selected}
    config["volumes"] = {name: {} for name in ("applicant-redis-data", "credential-redis-data")}
    gateway = config["services"]["gateway-service"]
    gateway["ports"] = [{"target": 8080, "published": str(args.port), "host_ip": "127.0.0.1", "protocol": "tcp"}]
    gateway["environment"].update(AUTH_API_KEYS=f"smoke:{KEY}", SD_POLL_INTERVAL_SECONDS="0.25")
    config["services"]["service-discovery"]["environment"].update(INSTANCE_TTL_SECONDS="6", POLL_INTERVAL_SECONDS="0.25")
    config["services"]["credential-service"]["environment"]["Services__UniversityRecordMode"] = "Mock"
    path.write_text(json.dumps(config), encoding="utf-8")
    compose = ["docker", "compose", "-p", project, "-f", str(path)]
    summary = {"project": project, "version": "0.4.0", "registry_dependency": "mocked", "checks": []}

    def rpc(url: str, method: str = "GET", body=None):
        # Execute from SD's private Docker network; no application health port is published.
        script = """import json,sys,urllib.request,urllib.error
p=json.load(sys.stdin)
r=urllib.request.Request(p['url'],data=json.dumps(p['body']).encode() if p['body'] is not None else None,method=p['method'],headers={'Content-Type':'application/json','X-Request-Id':'lab3-smoke-trace'})
try: response=urllib.request.urlopen(r,timeout=8)
except urllib.error.HTTPError as e: response=e
raw=response.read().decode()
print(json.dumps({'status':response.status,'body':json.loads(raw) if raw else None,'requestId':response.headers.get('X-Request-Id')}))
"""
        result = command(compose + ["exec", "-T", "service-discovery", "python", "-c", script], input=json.dumps({"url": url, "method": method, "body": body}), stderr=subprocess.DEVNULL)
        return json.loads(result)

    def instances(service):
        return rpc(f"http://localhost:8089/services/{service}/instances")["body"]["instances"]

    def proxy(path: str, body=None):
        return rpc("http://gateway-service:8090" + path, "POST" if body is not None else "GET", body)

    try:
        subprocess.check_call(compose + ["up", "-d", "--wait", "--wait-timeout", "90"])
        for service in ("applicant-service", "credential-service"):
            found = wait_for(lambda: (items if len(items := instances(service)) == 2 else None), f"two registered {service}")
            assert len({entry["url"] for entry in found}) == 2
            assert len({entry["instanceId"] for entry in found}) == 2
            for entry in found:
                health = rpc(entry["healthUrl"])
                assert health["status"] == 200 and health["body"]["version"] == "0.4.0"
                assert health["body"]["instanceId"] == entry["instanceId"]
                assert health["body"]["load"] == "NORMAL"
            summary["checks"].append(f"{service}: two unique healthy registered replicas")

        # Public auth remains enforced; internal traffic is used only from the private network.
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{args.port}/applicants", timeout=5)
            raise AssertionError("Public route admitted missing API key")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        request = urllib.request.Request(f"http://127.0.0.1:{args.port}/applicants", headers={"Authorization": f"Bearer {KEY}"})
        assert urllib.request.urlopen(request, timeout=5).status == 200
        summary["checks"].append("public auth rejects missing key and accepts fixture key")

        applicant = proxy("/applicants/generate", {"sessionId": str(uuid.uuid4()), "difficulty": "EASY"})
        assert applicant["status"] == 201, applicant
        assert applicant["requestId"] == "lab3-smoke-trace"
        for entry in instances("applicant-service"):
            assert rpc(entry["url"] + "/applicants/" + applicant["body"]["id"])["status"] == 200
        for entry in instances("credential-service"):
            assert rpc(entry["url"] + "/credentials/" + applicant["body"]["credentialId"])["status"] == 200
        for _ in range(4):
            assert proxy("/applicants")["status"] == 200
        logs = command(compose + ["logs", "--no-color", "gateway-service"])
        for entry in instances("applicant-service"):
            assert entry["url"] in logs, "Gateway did not route to both applicant replicas"
        for service in ("applicant-service", "credential-service"):
            service_logs = command(compose + ["logs", "--no-color", service])
            assert "request=lab3-smoke-trace" in service_logs, "Missing cross-service request log scope"
            assert KEY not in service_logs, "Authorization fixture leaked into service logs"
            for entry in instances(service):
                assert "instance=" + entry["instanceId"] in service_logs
        summary["checks"].append("real applicant-to-credential call, shared Redis reads, round-robin, and visible request/instance log IDs")

        subprocess.check_call(compose + ["up", "-d", "--no-deps", "--scale", "applicant-service=3", "applicant-service"])
        wait_for(lambda: len(instances("applicant-service")) == 3, "third replica registration")
        subprocess.check_call(compose + ["up", "-d", "--no-deps", "--scale", "applicant-service=2", "applicant-service"])
        wait_for(lambda: len(instances("applicant-service")) == 2, "shutdown deregistration")
        summary["checks"].append("dynamic scale 2 -> 3 -> 2 with registration/deregistration")

        subprocess.check_call(compose + ["restart", "service-discovery"])
        wait_for(lambda: len(instances("applicant-service")) == 2 and len(instances("credential-service")) == 2, "re-registration after SD restart")
        summary["checks"].append("heartbeat 404 triggers re-registration after SD restart")

        # Trip both applicant circuits through real failed calls; never auto-retry a business POST.
        subprocess.check_call(compose + ["stop", "credential-service"])
        for _ in range(6):
            response = proxy("/applicants/generate", {"sessionId": str(uuid.uuid4()), "difficulty": "EASY"})
            assert response["status"] == 503, response
        logs = command(compose + ["logs", "--no-color", "applicant-service"])
        assert "Circuit OPEN" in logs
        subprocess.check_call(compose + ["start", "credential-service"])
        wait_for(lambda: len(instances("credential-service")) == 2, "credential restart registration")
        wait_for(lambda: proxy("/applicants/generate", {"sessionId": str(uuid.uuid4()), "difficulty": "EASY"})["status"] == 201,
                 "half-open recovery after dependency restart", seconds=35)
        summary["checks"].append("real dependency failures trip applicant circuit; recovery succeeds after restart")
        print(json.dumps(summary, indent=2))
        (directory / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Evidence: {directory / 'result.json'}")
    finally:
        # Unique per-run project and volumes; never targets an existing user's Compose project.
        subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], check=True)


if __name__ == "__main__":
    main()
