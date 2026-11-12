import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("lab4_release", Path(__file__).resolve().parents[1] / "scripts/check_lab4_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class Lab4ReleaseGateTests(unittest.TestCase):
    def config(self):
        services = {service: {"image": image} for service, image in release.lab3.IMAGES.items()}
        for service in ("applicant-service", "credential-service"):
            services[service].update(deploy={"replicas": 2}, environment={"Storage__Provider": "Redis", "ServiceDiscovery__Url": "http://service-discovery:8089"})
        services["message-broker"] = {"image": release.BROKER_IMAGE, "environment": {"DISCOVERY_URL": "http://service-discovery:8089"},
                                      "volumes": [{"type": "volume", "source": "broker-data", "target": "/data"}]}
        services["player-service"]["environment"] = {"MESSAGING_ENABLED": "true"}
        for service in ("server-rules-service", "university-record-service"):
            services[service]["environment"] = {"BROKER_GRPC_URL": "message-broker:9091"}
        services["server-moderation-session-service"]["environment"] = {
            "MESSAGING_ENABLED": "true", "MESSAGING_BROKER_ADDRESS": "message-broker:9091",
            "DMS_CLIENT_MODE": "broker", "APPLICANT_CLIENT_MODE": "http", "RULES_CLIENT_MODE": "http"}
        return {"services": services}

    def test_the_wired_lab4_stack_passes(self):
        self.assertEqual([], release.validate_config(self.config()))
        config = self.config()
        config["services"]["server-moderation-session-service"]["environment"].update(
            APPLICANT_CLIENT_MODE="broker", RULES_CLIENT_MODE="broker")
        self.assertEqual([], release.validate_config(config))

    def test_the_broker_must_be_there_pinned_private_single_and_registered(self):
        for mutate, expected in [
            (lambda c: c["services"].pop("message-broker"), "message-broker: missing from Compose"),
            (lambda c: c["services"]["message-broker"].update(image="drateeva/message-broker:0.4.0"), "message-broker: expected drateeva/message-broker:0.5.0"),
            (lambda c: c["services"]["message-broker"].update(build="."), "message-broker: root Compose must use the published image, not a build context"),
            (lambda c: c["services"]["message-broker"].update(ports=[{"target": 9091}]), "message-broker: HTTP 8091 and gRPC 9091 must stay private to the Compose network"),
            (lambda c: c["services"]["message-broker"].update(deploy={"replicas": 2}), "message-broker: one instance only (its topic queues are one SQLite file)"),
            (lambda c: c["services"]["message-broker"].pop("volumes"), "message-broker: a named volume must be mounted on /data (durable queues and dead letters)"),
            (lambda c: c["services"]["message-broker"].update(volumes=[{"type": "bind", "source": "./data", "target": "/data"}]), "message-broker: a named volume must be mounted on /data (durable queues and dead letters)"),
            (lambda c: c["services"]["message-broker"]["environment"].pop("DISCOVERY_URL"), "message-broker: DISCOVERY_URL must be http://service-discovery:8089"),
        ]:
            config = self.config()
            mutate(config)
            self.assertIn(expected, release.validate_config(config))

    def test_player_and_session_must_use_the_broker(self):
        for service, key, value in [
            ("player-service", "MESSAGING_ENABLED", "false"),
            ("server-moderation-session-service", "MESSAGING_ENABLED", "false"),
            ("server-moderation-session-service", "MESSAGING_BROKER_ADDRESS", "localhost:9091"),
            ("server-moderation-session-service", "DMS_CLIENT_MODE", "http"),
            ("server-moderation-session-service", "APPLICANT_CLIENT_MODE", "mock"),
            ("server-moderation-session-service", "RULES_CLIENT_MODE", "mock"),
        ]:
            config = self.config()
            config["services"][service]["environment"][key] = value
            errors = release.validate_config(config)
            self.assertTrue(any(error.startswith(service) and key in error for error in errors), (service, key, errors))

    def test_no_rest_stand_in_in_compose(self):
        config = self.config()
        config["services"]["player-service"]["environment"]["MOCK_EVENTS_ENABLED"] = "true"
        self.assertIn("player-service: MOCK_EVENTS_ENABLED must not be on in Compose (REST stand-ins are local only)",
                      release.validate_config(config))

    def test_java_services_require_a_nonempty_broker_target_at_startup(self):
        for service in ("server-rules-service", "university-record-service"):
            for target in (None, "", "localhost:9091"):
                with self.subTest(service=service, target=target):
                    config = self.config()
                    env = config["services"][service]["environment"]
                    if target is None:
                        env.pop("BROKER_GRPC_URL")
                    else:
                        env["BROKER_GRPC_URL"] = target
                    self.assertTrue(any(service in error and "BROKER_GRPC_URL" in error
                                        for error in release.validate_config(config)))

    def test_lab3_rules_still_apply(self):
        config = self.config()
        config["services"]["gateway-service"]["image"] = "diana7376/gateway-service:0.3.0"
        self.assertIn(f"gateway-service: expected {release.lab3.IMAGES['gateway-service']}", release.validate_config(config))

    def test_publication_check_covers_the_broker(self):
        self.assertEqual(release.BROKER_IMAGE, release.images()["message-broker"])
        self.assertEqual(len(release.lab3.IMAGES) + 1, len(release.images()))


if __name__ == "__main__":
    unittest.main()
