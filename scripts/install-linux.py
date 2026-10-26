"""Install the reconnecting band service for the current Linux user."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
HOOK_STATUS = "Review command on Mi Band"


def unit_quote(value):
    value = str(value)
    if any(char in value for char in "\n\r\0"):
        raise ValueError("Invalid path in service configuration")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def service_unit(root):
    return f"""[Unit]
Description=Bracer Mi Band Codex approval connection

[Service]
Type=exec
WorkingDirectory={str(root).replace('%', '%%')}
ExecStart={unit_quote(root / '.venv/bin/python')} -u -m miband_agent --config {unit_quote(root / '.env')} serve
Restart=on-failure
RestartSec=3
RuntimeDirectory=miband-agent
RuntimeDirectoryMode=0700
UMask=0077

[Install]
WantedBy=default.target
"""


def merge_codex_hook(existing, root):
    data = json.loads(json.dumps(existing))
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError("Existing hooks.json must contain an object with a hooks object")
    events = data.setdefault("hooks", {})
    groups = events.get("PermissionRequest", [])
    if not isinstance(groups, list):
        raise ValueError("PermissionRequest hooks must be a list")
    retained = []
    for group in groups:
        handlers = group.get("hooks", [])
        kept = [handler for handler in handlers if not (
            handler.get("statusMessage") == HOOK_STATUS and "codex_approval_hook.py" in handler.get("command", ""))]
        if kept or not handlers:
            retained.append({**group, "hooks": kept})
    retained.append({"matcher": "^Bash$", "hooks": [{
        "type": "command",
        "command": shlex.join([str(root / ".venv/bin/python"), str(root / "scripts/codex_approval_hook.py")]),
        "timeout": 180,
        "statusMessage": HOOK_STATUS,
    }]})
    events["PermissionRequest"] = retained
    return data


def install_codex_hook(root):
    directory = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    target = directory / "hooks.json"
    previous = target.read_text() if target.exists() else None
    updated = json.dumps(merge_codex_hook(json.loads(previous) if previous else {}, root), indent=2) + "\n"
    if previous != updated:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if previous is not None:
            backup = directory / f"hooks.json.miband-backup-{time.time_ns()}"
            descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(previous)
            print(f"Existing hook configuration backed up at {backup}")
        temporary = directory / f".hooks.json.miband-{os.getpid()}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(updated)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"Installed global Codex command-approval hook: {target}")
    print("One-time Codex setup: open /hooks and review/trust 'Review command on Mi Band'.")
    print("Then open or resume normal local Codex chats; no bridge run command is needed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the unit without installing or starting it")
    parser.add_argument("--without-codex-hook", action="store_true", help="Install only the Bluetooth service")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit("This installer requires Linux with a systemd user session")
    if not (ROOT / ".venv/bin/python").is_file() or not (ROOT / ".env").is_file():
        raise SystemExit("Install dependencies and run band setup first")
    unit = service_unit(ROOT)
    if args.dry_run:
        print(unit, end="")
        return
    directory = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "systemd/user"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "miband-agent.service"
    target.write_text(unit)
    subprocess.run(["systemd-analyze", "--user", "verify", str(target)], check=True)
    if not args.without_codex_hook:
        install_codex_hook(ROOT)
        subprocess.run([str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/check_codex_hook.py")],
                       cwd=ROOT, check=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "miband-agent.service"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "miband-agent.service"], check=True)
    subprocess.run(["systemctl", "--user", "is-enabled", "miband-agent.service"], check=True)
    subprocess.run(["systemctl", "--user", "is-active", "miband-agent.service"], check=True)
    print("Installed and started miband-agent.service; it will start at login.")
    for _ in range(20):
        result = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "miband_agent", "status"],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode == 0:
            print("Connection:", result.stdout.strip())
            break
        time.sleep(0.1)
    else:
        print("Service started; check connection: .venv/bin/python -m miband_agent status")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Service installation failed: {error}. Run this installer from your normal host terminal.") from None
