"""Copy the installed Zepp Life APKs to the laptop for offline inspection."""

import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    adb = root / ".tools/platform-tools/adb"
    command = [str(adb), "-s", args.serial]
    result = subprocess.run(command + ["shell", "pm", "path", "com.xiaomi.hm.health"],
                            check=True, capture_output=True, text=True)
    paths = [line.removeprefix("package:").strip() for line in result.stdout.splitlines()
             if line.startswith("package:")]
    if not paths or any(not path.startswith("/") or not path.endswith(".apk") for path in paths):
        raise RuntimeError("Zepp Life APK paths were not found; keep the phone connected and authorized")
    output = root / ".tools/zepp-apk"
    output.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(paths):
        filename = "base.apk" if path.endswith("/base.apk") else f"split-{index:03d}.apk"
        subprocess.run(command + ["pull", path, str(output / filename)], check=True)
    print(f"Copied {len(paths)} APK file(s) to {output}")
    print("Copied app installers only. No app installation, removal, or private-data extraction was performed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Export failed: {error}", file=sys.stderr)
        sys.exit(1)
