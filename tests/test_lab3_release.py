import importlib.util
from pathlib import Path
import unittest
from unittest.mock import call, patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[1] / "scripts/check_lab3_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseGateTests(unittest.TestCase):
    def config(self):
        services = {service: {"image": image} for service, image in release.IMAGES.items()}
        for service in ("applicant-service", "credential-service"):
            services[service].update(deploy={"replicas": 2}, environment={"Storage__Provider": "Redis", "ServiceDiscovery__Url": "http://service-discovery:8089"})
        return {"services": services}

    def test_complete_release_and_mixed_version(self):
        config = self.config()
        self.assertEqual([], release.validate_config(config))
        config["services"]["applicant-service"]["image"] = "caramisca/applicant-service:0.3.0"
        self.assertTrue(release.validate_config(config))

    def test_missing_registry_private_ports_and_local_build_are_rejected(self):
        for mutate in [lambda c: c["services"].pop("service-discovery"),
                       lambda c: c["services"]["service-discovery"].update(ports=[{"target": 8089}]),
                       lambda c: c["services"]["applicant-service"].update(build="."),
                       lambda c: c["services"]["gateway-service"].update(ports=[{"target": 8090}])]:
            config = self.config()
            mutate(config)
            self.assertTrue(release.validate_config(config))

    def test_independent_patch_versions_accept_mixed_release_and_reject_wrong_service_tag(self):
        with patch.dict(release.IMAGES, {
            "gateway-service": "diana7376/gateway-service:0.4.1",
            "applicant-service": "caramisca/applicant-service:0.4.0",
        }):
            config = self.config()
            self.assertEqual("caramisca/applicant-service:0.4.0", config["services"]["applicant-service"]["image"])
            self.assertEqual([], release.validate_config(config))
            config["services"]["gateway-service"]["image"] = "diana7376/gateway-service:0.4.0"
            self.assertIn("gateway-service: expected diana7376/gateway-service:0.4.1", release.validate_config(config))
            config["services"]["gateway-service"]["image"] = "diana7376/gateway-service:0.4.1"
            config["services"]["applicant-service"]["image"] = "caramisca/applicant-service:0.4.1"
            self.assertIn("applicant-service: expected caramisca/applicant-service:0.4.0", release.validate_config(config))

    def test_public_manifest_requires_both_platforms_and_matching_latest(self):
        metadata = {"digest": "sha256:test", "images": [{"os": "linux", "architecture": a} for a in ["amd64", "arm64"]]}
        with patch.object(release, "tag_metadata", return_value=metadata):
            self.assertEqual([], release.validate_public_image("test/image:0.4.0"))
        bad_latest = {**metadata, "digest": "sha256:other"}
        with patch.object(release, "tag_metadata", side_effect=[metadata, bad_latest]):
            self.assertTrue(release.validate_public_image("test/image:0.4.0"))

    def test_public_manifest_uses_the_services_patch_tag_and_requires_both_platforms(self):
        metadata = {"digest": "sha256:patch", "images": [{"os": "linux", "architecture": a} for a in ["amd64", "arm64"]]}
        with patch.object(release, "tag_metadata", return_value=metadata) as lookup:
            self.assertEqual([], release.validate_public_image("test/image:0.4.1"))
            self.assertEqual([call("test/image", "0.4.1"), call("test/image", "latest")], lookup.call_args_list)
        missing_arm = {**metadata, "images": [{"os": "linux", "architecture": "amd64"}]}
        with patch.object(release, "tag_metadata", return_value=missing_arm):
            self.assertIn("test/image:0.4.1: missing linux/amd64 or linux/arm64", release.validate_public_image("test/image:0.4.1"))

    def test_unpublished_patch_release_fails_without_falling_back(self):
        missing = HTTPError("https://hub.docker.com/test", 404, "Not Found", None, None)
        with patch.object(release, "tag_metadata", side_effect=missing) as lookup:
            self.assertEqual(["test/image:0.4.1: public DockerHub lookup returned HTTP 404"], release.validate_public_image("test/image:0.4.1"))
            lookup.assert_called_once_with("test/image", "0.4.1")


if __name__ == "__main__":
    unittest.main()
