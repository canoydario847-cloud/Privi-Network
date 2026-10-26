#!/usr/bin/env python3
"""Offline Google Play / Trusted Web Activity configuration checks.

This intentionally does NOT claim a deployed domain is reachable, a certificate
matches Google Play App Signing, or an app is published. All require separate
verification in the developer account and on the actual HTTPS website.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
SHA256_FINGERPRINT = re.compile(r"^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$")


def validate(root: Path = REPO) -> list[str]:
    errors: list[str] = []
    strings_path = root / "android-app/app/src/main/res/values/strings.xml"
    gradle_path = root / "android-app/app/build.gradle.kts"
    app_manifest_path = root / "android-app/app/src/main/AndroidManifest.xml"
    assetlinks_path = root / "sites/home/.well-known/assetlinks.json"
    web_manifest_path = root / "sites/home/manifest.webmanifest"
    privacy_path = root / "sites/home/privacy.html"

    try:
        strings_root = ET.parse(strings_path).getroot()
        strings = {s.get("name"): (s.text or "").strip() for s in strings_root.findall("string")}
        gradle = gradle_path.read_text(encoding="utf-8")
        app_manifest = ET.parse(app_manifest_path).getroot()
        assetlinks = json.loads(assetlinks_path.read_text(encoding="utf-8"))
        web_manifest = json.loads(web_manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ET.ParseError, ValueError, OSError) as exc:
        return [f"Invalid or missing Play prerequisite file: {exc}"]

    match = re.search(r'\\bapplicationId\\s*=\\s*"([^"]+)"', gradle)
    pkg = match.group(1) if match else ""
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*(?:\\.[a-zA-Z][a-zA-Z0-9_]*)+", pkg):
        errors.append("Android applicationId must be a valid package name")

    host = strings.get("hostName", "")
    launch_url = strings.get("launchUrl", "")
    parsed = urlsplit(launch_url)
    if parsed.scheme != "https" or parsed.hostname != host or parsed.username or parsed.password:
        errors.append("Android launchUrl must use HTTPS and match hostName")
    if not host or "/" in host or host.lower() != host:
        errors.append("Android hostName must be one lowercase hostname")

    try:
        asset_statements = json.loads(strings.get("assetStatements", "").replace('\\\\"', '"'))
        matches = any(
            statement.get("target", {}).get("namespace") == "web"
            and statement.get("target", {}).get("site") == f"https://{host}"
            and "delegate_permission/common.handle_all_urls" in statement.get("relation", [])
            for statement in asset_statements
        )
        if not matches:
            errors.append("Android assetStatements web origin does not match hostName")
    except (TypeError, ValueError, AttributeError):
        errors.append("Android assetStatements must contain valid JSON")

    if not isinstance(assetlinks, list) or not assetlinks:
        errors.append("Web assetlinks.json must contain nonempty statements")
    else:
        found = False
        for statement in assetlinks:
            if not isinstance(statement, dict):
                continue
            target = statement.get("target", {})
            if not isinstance(target, dict) or target.get("package_name") != pkg:
                continue
            if target.get("namespace") != "android_app":
                continue
            if "delegate_permission/common.handle_all_urls" not in statement.get("relation", []):
                continue
            fingerprints = target.get("sha256_cert_fingerprints", [])
            if isinstance(fingerprints, list) and fingerprints and all(
                isinstance(fingerprint, str) and SHA256_FINGERPRINT.fullmatch(fingerprint)
                for fingerprint in fingerprints
            ):
                found = True
        if not found:
            errors.append("Web assetlinks.json must match package and have valid SHA-256 fingerprint(s)")

    if app_manifest.find(".//activity[@{http://schemas.android.com/apk/res/android}name='com.google.androidbrowserhelper.trusted.LauncherActivity']") is None:
        errors.append("Android Manifest must declare a Trusted Web Activity launcher")
    if (web_manifest.get("display") not in ("standalone", "fullscreen")
            or not web_manifest.get("start_url") or not web_manifest.get("icons")):
        errors.append("Web app manifest must declare standalone display, start_url and icons")
    if not privacy_path.is_file():
        errors.append("A public privacy policy source file is required")
    return errors


if __name__ == "__main__":
    failures = validate()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        sys.exit(1)
    print("PASS: Offline Privi Android/Google Play configuration is internally consistent.")
    print("NOT VERIFIED: Live HTTPS URLs, current Google Play signing certificate, Google account,")
    print("              AAB upload signature, privacy declarations, or Play release approval.")
