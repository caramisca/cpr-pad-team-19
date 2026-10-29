"""Exercise Mihai's Lab 3 images in a fresh, isolated Compose project.

Requires locally available 0.4.0 images (reviewed/published images or explicitly built PR images).
The university registry is mocked unless --real-registry is selected; this is not a full-team E2E test.
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
    parser.add_argument("--sd-image", help="Explicit local SD PR-build tag; root release Compose is unchanged")
    parser.add_argument("--gateway-image", help="Explicit local Gateway PR-build tag")
    parser.add_argument("--real-registry", action="store_true", help="Include published University Record and its real PostgreSQL")
    parser.add_argument("--output", type=Path, help="Also save the successful result JSON at this path")
    args = parser.parse_args()
    project = "pad-lab3-smoke-" + uuid.uuid4().hex[:8]
    directory = Path(tempfile.mkdtemp(prefix=project + "-"))
    path = directory / "compose.json"
    config = json.loads(command(["docker", "compose", "--env-file", str(ROOT / ".env.example"), "-f", str(ROOT / "docker-compose.yml"), "config", "--format", "json"]))
    selected = {"service-discovery", "gateway-service", "applicant-service", "credential-service", "applicant-redis", "credential-redis", "applicant-seed", "credential-seed"}
    if args.real_registry:
        selected.update(("university-record-service", "record-postgres"))
    config["services"] = {name: value for name, value in config["services"].items() if name in selected}
    if args.sd_image:
        config["services"]["service-discovery"]["image"] = args.sd_image
    if args.gateway_image:
        config["services"]["gateway-service"]["image"] = args.gateway_image
    config.pop("name", None)
    config["networks"] = {"default": {}}
    for value in config["services"].values():
        value["pull_policy"] = "never"
        value["depends_on"] = {name: settings for name, settings in value.get("depends_on", {}).items() if name in selected}
    config["volumes"] = {name: {} for name in ("applicant-redis-data", "credential-redis-data")}
    if args.real_registry:
        config["volumes"]["record-postgres-data"] = {}
    gateway = config["services"]["gateway-service"]
    gateway["ports"] = [{"target": 8080, "published": str(args.port), "host_ip": "127.0.0.1", "protocol": "tcp"}]
    gateway["environment"].update(AUTH_API_KEYS=f"smoke:{KEY}", SD_POLL_INTERVAL_SECONDS="0.25")
    config["services"]["service-discovery"]["environment"].update(
        INSTANCE_TTL_SECONDS="6", POLL_INTERVAL_SECONDS="0.25",
        ALERT_DISCORD_WEBHOOK_URL="http://service-discovery:18091/webhook",
        ALERT_TELEGRAM_BOT_TOKEN="", ALERT_TELEGRAM_CHAT_ID="",
    )
    config["services"]["credential-service"]["environment"]["Services__UniversityRecordMode"] = "Http" if args.real_registry else "Mock"
    path.write_text(json.dumps(config), encoding="utf-8")
    compose = ["docker", "compose", "-p", project, "-f", str(path)]
    summary = {"project": project, "version": "0.4.0", "registry_dependency": "real" if args.real_registry else "mocked", "checks": [],
               "images": {name: {"reference": value["image"],
                                  "id": command(["docker", "image", "inspect", "--format", "{{.Id}}", value["image"]])}
                          for name, value in config["services"].items() if name in
                          ("service-discovery", "gateway-service", "applicant-service", "credential-service", "university-record-service")}}

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
        if args.real_registry:
            wait_for(lambda: rpc("http://university-record-service:8086/health")["status"] == 200,
                     "real University Record health and PostgreSQL migrations", seconds=90)
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
        if args.real_registry:
            assert proxy("/records/faculties")["status"] == 200
            issued = proxy("/credentials/issue", {"applicantId": str(uuid.uuid4()), "isLegitimate": True,
                                                  "seed": {"studentId": "1234567890", "faculty": "FAF", "year": 3}})
            assert issued["status"] == 201, issued
            assert issued["body"]["fields"]["fullName"] == "Diana Popescu"
            registry_logs = command(compose + ["logs", "--no-color", "university-record-service"])
            assert "/records/students/lookup" in registry_logs, "Credential did not call the real registry"
            summary["checks"].append("real Applicant -> Gateway -> Credential -> Gateway -> University Record call with PostgreSQL")
            summary["record_instances"] = instances("university-record-service")
            if not summary["record_instances"]:
                summary["limitations"] = ["University Record had no registered SD instances at lookup; real dependency calls used Gateway static fallback, not discovered-instance load balancing."]

        subprocess.check_call(compose + ["up", "-d", "--no-deps", "--scale", "applicant-service=3", "applicant-service"])
        wait_for(lambda: len(instances("applicant-service")) == 3, "third replica registration")
        subprocess.check_call(compose + ["up", "-d", "--no-deps", "--scale", "applicant-service=2", "applicant-service"])
        wait_for(lambda: len(instances("applicant-service")) == 2, "shutdown deregistration")
        summary["checks"].append("dynamic scale 2 -> 3 -> 2 with registration/deregistration")

        subprocess.check_call(compose + ["restart", "service-discovery"])
        wait_for(lambda: len(instances("applicant-service")) == 2 and len(instances("credential-service")) == 2, "re-registration after SD restart")
        summary["checks"].append("heartbeat 404 triggers re-registration after SD restart")

        # A fixture fails business GETs while keeping /health healthy: only Gateway G10 removes it.
        # It runs inside this test's private SD container and sends no external traffic.
        fixture = """import json
from http.server import BaseHTTPRequestHandler, HTTPServer
calls = 0
alerts = []
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global calls
        if self.path == '/health':
            status, body = 200, {'load': 'NORMAL', 'activeThreads': 0, 'maxThreads': 10}
        elif self.path == '/metrics':
            status, body = 200, {'calls': calls}
        elif self.path == '/critical':
            status, body = 200, {'load': 'CRITICAL', 'activeThreads': 9, 'maxThreads': 10}
        elif self.path == '/alerts':
            status, body = 200, {'alerts': alerts}
        else:
            calls += 1
            status, body = 503, {'error': 'SMOKE_FAILURE', 'message': 'Controlled failing replica'}
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        alerts.append(json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0')))))
        self.send_response(204)
        self.end_headers()
    def log_message(self, *args): pass
HTTPServer(('0.0.0.0', 18091), Handler).serve_forever()
"""
        command(compose + ["exec", "-d", "-T", "service-discovery", "python", "-c", fixture])
        fixture_url = "http://service-discovery:18091"
        wait_for(lambda: rpc(fixture_url + "/health")["status"] == 200, "failing-instance fixture")
        bad_id = "lab3-failing-fixture"
        registration = {"serviceName": "applicant-service", "instanceId": bad_id, "url": fixture_url}
        assert rpc("http://localhost:8089/instances", "POST", registration)["status"] == 201
        failures = []

        def removed_after_three_failures():
            # Keep the fixture alive until Gateway explicitly deregisters it; TTL is not eviction.
            rpc(f"http://localhost:8089/instances/applicant-service/{bad_id}/heartbeat", "PUT")
            response = proxy("/applicants")
            assert response["status"] in (200, 503), response
            if response["status"] == 503:
                assert response["body"]["error"] == "SMOKE_FAILURE", response
                failures.append(time.monotonic())
            return len(failures) == 3 and all(i["instanceId"] != bad_id for i in instances("applicant-service"))

        wait_for(removed_after_three_failures, "G10 deregistration of the failing physical instance", seconds=30)
        window = float(gateway["environment"]["REQUEST_TIMEOUT_SECONDS"]) * 3.5
        assert failures[-1] - failures[0] <= window
        logs = command(compose + ["logs", "--no-color", "gateway-service"])
        assert f"Removed instance {bad_id} of applicant-service" in logs
        assert rpc(fixture_url + "/metrics")["body"]["calls"] == 3
        for _ in range(6):
            assert proxy("/applicants")["status"] == 200
        assert rpc(fixture_url + "/metrics")["body"]["calls"] == 3
        assert len(instances("applicant-service")) == 2
        summary["checks"].append("G10: three physical-instance failures cause SD deregistration and round-robin removal; both healthy replicas keep serving")

        alert_instance = {"serviceName": "lab3-alert-fixture", "instanceId": "critical-fixture", "url": fixture_url,
                          "healthUrl": fixture_url + "/critical"}
        assert rpc("http://localhost:8089/instances", "POST", alert_instance)["status"] == 201
        wait_for(lambda: any("CRITICAL LOAD: lab3-alert-fixture" in a.get("content", "")
                             for a in rpc(fixture_url + "/alerts")["body"]["alerts"]),
                 "critical load travels from SD polling through the real HTTP notifier to the local webhook fixture")
        assert rpc("http://localhost:8089/instances/lab3-alert-fixture/critical-fixture", "DELETE")["status"] == 204
        summary["checks"].append("G8/G9: critical health load triggers an HTTP Discord notification to an isolated webhook fixture; no real developer channel used")

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
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Evidence: {directory / 'result.json'}")
    finally:
        # Unique per-run project and volumes; never targets an existing user's Compose project.
        subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], check=True)


if __name__ == "__main__":
    main()
