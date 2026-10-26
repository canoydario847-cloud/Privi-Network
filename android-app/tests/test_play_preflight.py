"""Synthetic regression checks for the Android Play preflight (no Google credentials)."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "android-app/scripts/play_preflight.py"
spec = importlib.util.spec_from_file_location("play_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)

FILES = [
    "android-app/app/build.gradle.kts",
    "android-app/app/src/main/res/values/strings.xml",
    "android-app/app/src/main/AndroidManifest.xml",
    "sites/home/.well-known/assetlinks.json",
    "sites/home/manifest.webmanifest",
    "sites/home/privacy.html",
]


class PlayPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for rel in FILES:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, target)

    def tearDown(self):
        self.temp.cleanup()

    def rewrite(self, rel, replace):
        path = self.root / rel
        current = path.read_text(encoding="utf-8")
        updated = replace(current)
        self.assertNotEqual(current, updated, "The test fixture must actually change")
        path.write_text(updated, encoding="utf-8")

    def test_existing_configuration_is_internally_consistent(self):
        self.assertEqual(preflight.validate(self.root), [])

    def test_rejects_insecure_launch_url(self):
        self.rewrite("android-app/app/src/main/res/values/strings.xml",
                     lambda t: t.replace("https://privi-world.onrender.com/?source=app",
                                         "http://privi-world.onrender.com/?source=app"))
        self.assertTrue(any("HTTPS" in e for e in preflight.validate(self.root)))

    def test_rejects_changed_host(self):
        self.rewrite("android-app/app/src/main/res/values/strings.xml",
                     lambda t: t.replace("<string name=\"hostName\">privi-world.onrender.com",
                                         "<string name=\"hostName\">other.example"))
        self.assertTrue(any("hostName" in e for e in preflight.validate(self.root)))

    def test_rejects_assetlinks_for_another_app(self):
        path = self.root / "sites/home/.well-known/assetlinks.json"
        obj = json.loads(path.read_text())
        obj[0]["target"]["package_name"] = "org.other.app"
        path.write_text(json.dumps(obj))
        self.assertTrue(any("assetlinks" in e for e in preflight.validate(self.root)))

    def test_rejects_bad_sha256_fingerprint(self):
        path = self.root / "sites/home/.well-known/assetlinks.json"
        obj = json.loads(path.read_text())
        obj[0]["target"]["sha256_cert_fingerprints"] = ["UNVERIFIED"]
        path.write_text(json.dumps(obj))
        self.assertTrue(any("SHA-256" in e for e in preflight.validate(self.root)))

    def test_rejects_missing_privacy_policy(self):
        (self.root / "sites/home/privacy.html").unlink()
        self.assertTrue(any("privacy" in e for e in preflight.validate(self.root)))


if __name__ == "__main__":
    unittest.main()
