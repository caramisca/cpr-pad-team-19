import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[1] / "scripts/check_lab3_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseGateTests(unittest.TestCase):
    def config(self):
        services = {service: {"image": f"{image}:0.4.0"} for service, image in release.IMAGES.items()}
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

    def test_public_manifest_requires_both_platforms_and_matching_latest(self):
        metadata = {"digest": "sha256:test", "images": [{"os": "linux", "architecture": a} for a in ["amd64", "arm64"]]}
        with patch.object(release, "tag_metadata", return_value=metadata):
            self.assertEqual([], release.validate_public_image("test/image"))
        bad_latest = {**metadata, "digest": "sha256:other"}
        with patch.object(release, "tag_metadata", side_effect=[metadata, bad_latest]):
            self.assertTrue(release.validate_public_image("test/image"))


if __name__ == "__main__":
    unittest.main()
