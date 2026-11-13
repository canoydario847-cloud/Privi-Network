#!/usr/bin/env python3
"""Generate the five Privi apps from apps.json.

For each app this writes
  <server package>/webapp.py            copy of apps/webapp.py
  <server package>/webapp/app.html      copy of apps/app.html
  <server package>/webapp/app.json      that app's settings
  <server package>/webapp/icon-*.png    web app icons
  android-<slug>/                       Trusted Web Activity project for Google Play
  .github/workflows/android-<slug>.yml  builds the .aab

Run from anywhere:  python3 apps/build.py     (needs Pillow for the icons)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
APPS = json.loads((ROOT / "apps" / "apps.json").read_text(encoding="utf-8"))
NAVY = (14, 27, 51)
DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def logo(accent: str) -> Image.Image:
    """The Privi mark on navy, with its dot in the app's accent color so the five icons can be told apart."""
    src = Image.open(ROOT / "assets" / "logo-400.png").convert("RGBA")
    flat = Image.new("RGBA", src.size, NAVY + (255,))
    flat.alpha_composite(src)
    px, a = flat.load(), rgb(accent)
    for y in range(flat.height):
        for x in range(flat.width):
            r, g, b, _ = px[x, y]
            if g > r + 50 and g > b + 20:                       # the green dot (and its soft edge)
                t = min(1.0, (g - max(r, b)) / 60)
                px[x, y] = tuple(round(NAVY[i] + (a[i] - NAVY[i]) * t) for i in range(3)) + (255,)
    return flat


def round_icon(img: Image.Image) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, img.width - 1, img.height - 1), fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_web(slug: str, app: dict, mark: Image.Image) -> None:
    pkg = ROOT / app["package_dir"]
    shutil.copyfile(ROOT / "apps" / "webapp.py", pkg / "webapp.py")
    out = pkg / "webapp"
    out.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "apps" / "app.html", out / "app.html")
    cfg = {"slug": slug, **{k: v for k, v in app.items() if k not in ("package_dir", "accent", "listing")}}
    write(out / "app.json", json.dumps(cfg, indent=1, ensure_ascii=False) + "\n")
    for size in (192, 512):
        mark.resize((size, size), Image.LANCZOS).convert("RGB").save(out / f"icon-{size}.png", optimize=True)


def build_android(slug: str, app: dict, mark: Image.Image) -> None:
    a, host = app["android"], app["host"]
    d = ROOT / a["dir"]
    res = d / "app" / "src" / "main" / "res"
    src = ROOT / "android-realcheck"
    for rel in ("build.gradle.kts", "gradle.properties", "app/src/main/AndroidManifest.xml",
                "app/src/main/res/values/colors.xml", "app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml",
                "app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml"):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / rel, d / rel)
    write(d / "settings.gradle.kts", (src / "settings.gradle.kts").read_text().replace("PriviRealCheck", a["project"]))
    gradle = (src / "app" / "build.gradle.kts").read_text()
    gradle = gradle.replace("us.priviflow.realcheck", a["package"]).replace(
        "Privi RealCheck for Android: a Trusted Web Activity that opens Privi RealCheck",
        f"{app['name']} for Android: a Trusted Web Activity that opens the {app['name']} web app")
    write(d / "app" / "build.gradle.kts", gradle)
    write(res / "values" / "strings.xml", f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="appName">{app['name']}</string>
    <string name="hostName">{host}</string>
    <string name="launchUrl">https://{host}/app/?source=app</string>
    <string name="assetStatements" translatable="false">
        [{{ \\"relation\\": [\\"delegate_permission/common.handle_all_urls\\"],
           \\"target\\": {{ \\"namespace\\": \\"web\\", \\"site\\": \\"https://{host}\\" }} }}]
    </string>
</resources>
""")
    for name, size in DENSITIES.items():
        icon = mark.resize((size, size), Image.LANCZOS)
        (res / f"mipmap-{name}").mkdir(parents=True, exist_ok=True)
        icon.save(res / f"mipmap-{name}" / "ic_launcher.png", optimize=True)
        round_icon(icon).save(res / f"mipmap-{name}" / "ic_launcher_round.png", optimize=True)
    fg = Image.new("RGBA", (432, 432), NAVY + (255,))
    inner = mark.resize((300, 300), Image.LANCZOS)
    fg.paste(inner, (66, 66))
    (res / "drawable").mkdir(parents=True, exist_ok=True)
    fg.save(res / "drawable" / "ic_launcher_foreground.png", optimize=True)
    mark.resize((512, 512), Image.LANCZOS).convert("RGB").save(d / "play-store-icon-512.png", optimize=True)

    env, up = a["fingerprint_env"], slug.upper()
    service = "privi-" + host.split(".")[0].removeprefix("privi-")
    write(d / "README.md", f"""# {app['name']} for Android

A Trusted Web Activity (TWA) that opens the {app['name']} web app (`https://{host}/app/`) full screen in Chrome.
The same app installs from any browser ("Add to Home screen" / "Install app") without Google Play.

- Package: `{a['package']}`
- Origin: `https://{host}` (the server serves `/.well-known/assetlinks.json` for it)
- Built by `.github/workflows/android-{slug}.yml` (unsigned unless signing secrets are set)
- Generated by `apps/build.py` from `apps/apps.json`. Change those, not the files here.

## Release steps (owner only)

1. **Upload key.** On your computer: `keytool -genkeypair -v -keystore {slug}-upload.jks -alias upload -keyalg RSA -keysize 2048 -validity 10000`.
   Keep the file and password safe and off GitHub. Optionally add GitHub secrets `{up}_KEYSTORE_B64` (base64 of the
   .jks) and `{up}_KEYSTORE_PASSWORD` so the workflow signs the bundle for you.
2. **Build.** GitHub → Actions → "{app['name']} Android app" → Run workflow. Download the `.aab` from the run.
3. **Play Console** (account PriviKing1) → Create app → "{app['name']}", App, Free to download → upload the .aab to
   **Internal testing**.
4. **App signing fingerprint.** Play Console → Test and release → App integrity → copy the **App signing key
   SHA-256**. In Render, set `{env}` on {service} to that value (comma-separate if you add the upload-key SHA-256
   too). Until this is set the app still works, but shows a browser bar at the top.
5. **Store listing, Data safety, content rating, privacy policy URL**, then roll out. Personal developer accounts
   must run a **closed test with at least 12 testers for 14 days** before Google allows a production release.

## Suggested listing

**Title:** {app['name']}
**Short description:** {app['listing']['short']}
**Full description:** {app['listing']['full']}
**Icon:** `play-store-icon-512.png` in this folder.

## Things to know before submitting

- Payment for the service happens on the web (a Privi key or plan, or USDC from a crypto wallet), not through
  Google Play billing. Check Google Play's current payments policy for your case before you submit.
- Pay-per-use with a wallet does not work inside the Play app itself, because Chrome on Android has no wallet. The
  app offers an "Open in MetaMask" link for that; customers with a key or plan are not affected.
""")
    wf = (ROOT / ".github" / "workflows" / "android-realcheck.yml").read_text()
    wf = (wf.replace("android-realcheck", f"android-{slug}").replace("Privi RealCheck", app["name"])
            .replace("us.priviflow.realcheck", a["package"])
            .replace("https://privi-quantum.onrender.com/real", f"https://{host}/app/")
            .replace("REALCHECK_KEYSTORE", f"{up}_KEYSTORE").replace("privi-realcheck", f"privi-{slug}")
            .replace("aab/realcheck-latest", f"aab/{slug}-latest").replace("Privi realcheck", f"Privi {slug}"))
    write(ROOT / ".github" / "workflows" / f"android-{slug}.yml", wf)


def main() -> None:
    for slug, app in APPS.items():
        mark = logo(app["accent"])
        build_web(slug, app, mark)
        build_android(slug, app, mark)
        print(f"{slug}: {app['package_dir']}/webapp, {app['android']['dir']}")


if __name__ == "__main__":
    main()
