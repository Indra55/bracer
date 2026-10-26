"""Optional mitmproxy addon for one-time capture of your own band's key.

MIBAND_ADDRESS=AA:BB:CC:DD:EE:FF mitmdump -s scripts/experimental/capture_key.py ...
No traffic, account tokens, or key values are printed or recorded.
"""

import json
import os
from pathlib import Path
import re


def normalized_address(value):
    if not isinstance(value, str):
        return None
    value = value.replace(":", "").replace("-", "").upper()
    return value if re.fullmatch(r"[0-9A-F]{12}", value) else None


def target_keys(data, address):
    found = set()
    if isinstance(data, dict):
        mac = next((normalized_address(data.get(name)) for name in
                    ("macAddress", "mac", "mac_address") if normalized_address(data.get(name))), None)
        if mac == address:
            extra = data.get("additionalInfo", {})
            if isinstance(extra, str):
                try:
                    extra = json.loads(extra)
                except ValueError:
                    extra = {}
            candidates = [data]
            if isinstance(extra, dict):
                candidates.append(extra)
            for candidate in candidates:
                for name in ("auth_key", "authKey"):
                    key = candidate.get(name)
                    if isinstance(key, str):
                        key = key.removeprefix("0x").lower()
                        if re.fullmatch(r"[0-9a-f]{32}", key):
                            found.add(key)
        for value in data.values():
            if isinstance(value, (dict, list)):
                found.update(target_keys(value, address))
    elif isinstance(data, list):
        for value in data:
            found.update(target_keys(value, address))
    return found


class KeyCapture:
    def __init__(self, address=None, output=None):
        self.address = normalized_address(address or os.environ.get("MIBAND_ADDRESS", ""))
        self.output = Path(output or os.environ.get("MIBAND_KEY_FILE", "auth-key.txt"))
        self.saved = False

    def running(self):
        if not self.address:
            raise ValueError("Set MIBAND_ADDRESS to your band's Bluetooth address first")
        print("Waiting for the selected band's key. Open Zepp Life and refresh its device page.", flush=True)

    def response(self, flow):
        if self.saved or not self.address or flow.response is None:
            return
        host = flow.request.pretty_host.lower().rstrip(".")
        if not any(host == domain or host.endswith("." + domain)
                   for domain in ("huami.com", "zepp.com", "amazfit.com", "xiaomi.com")):
            return
        path = flow.request.path.split("?", 1)[0]
        if not any(part in {"devices", "device"} for part in path.split("/")):
            return
        try:
            data = json.loads(flow.response.get_text(strict=False))
        except (ValueError, TypeError):
            return
        keys = target_keys(data, self.address)
        if not keys:
            return
        if len(keys) != 1:
            print("Conflicting keys for the selected band; no file saved.", flush=True)
            return
        try:
            descriptor = os.open(self.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            print("Key output file already exists; refusing to overwrite it. Stop capture and check it locally.", flush=True)
            self.saved = True
            return
        with os.fdopen(descriptor, "w") as output:
            output.write(next(iter(keys)) + "\n")
        self.saved = True
        print("Band key saved with owner-only permissions. Stop capture and remove the phone proxy and certificate.", flush=True)


addons = [KeyCapture()]
