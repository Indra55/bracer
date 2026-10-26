"""Retrieve a band key using the source version of argrento/huami-token."""

import getpass
import json
import os
from pathlib import Path
import re
import sys
import uuid
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from miband_agent.config import read_env


def load_credentials(path):
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise SystemExit("Credential file must have owner-only permissions (chmod 600).")
        data = read_env(path)
        email, password = data.get("ZEPP_EMAIL"), data.get("ZEPP_PASSWORD")
        if not email and not password:
            return input("Zepp Life email: ").strip(), getpass.getpass("Zepp Life password (hidden): ")
        if not isinstance(email, str) or not email or not isinstance(password, str) or not password:
            raise SystemExit(".env needs both ZEPP_EMAIL and ZEPP_PASSWORD, or leave both empty to prompt.")
        print("Using saved local credentials.")
        return email, password
    return input("Zepp Life email: ").strip(), getpass.getpass("Zepp Life password (hidden): ")


def configure_zepp_life():
    from huami_token.constants import PAYLOADS

    # Keep the working account-token exchange, but request a Mi Fit/Zepp Life session.
    payload = PAYLOADS.ZEPP_LOGIN.value
    payload["app_name"] = "com.xiaomi.hm.health"
    payload.pop("source", None)
    payload.pop("app_version", None)


def make_session(email, password):
    import requests
    from huami_token.constants import HEADERS, PAYLOADS, URLS
    from huami_token.errors import AuthenticationError
    from huami_token.zepp import ZeppSession

    class DiagnosticSession(ZeppSession):
        def _login(self):
            payload = PAYLOADS.ZEPP_LOGIN.value.copy()
            payload.update(code=self._access_token, device_id=str(uuid.uuid4()))
            response = requests.post(
                URLS.ZEPP_LOGIN.value, data=payload,
                headers=HEADERS.ZEPP_LOGIN.value,
                timeout=30, allow_redirects=False,
            )
            print(f"Application-session login: HTTP {response.status_code}")
            try:
                data = response.json()
            except ValueError:
                raise AuthenticationError(code="login-response-not-json") from None
            if not isinstance(data, dict):
                raise AuthenticationError(code="login-response-invalid")
            # Only numeric status codes are safe to expose from an error response.
            for field in ("code", "error_code", "errorCode", "status"):
                value = data.get(field)
                if isinstance(value, (str, int)) and re.fullmatch(r"-?\d{1,8}", str(value)):
                    print(f"Server {field}: {value}")
            if response.status_code != 200:
                raise AuthenticationError(code=f"login-http-{response.status_code}")
            info = data.get("token_info")
            if not isinstance(info, dict):
                raise AuthenticationError(code="no-token-info")
            self._login_token = info.get("login_token")
            self._app_token = info.get("app_token")
            self._user_id = info.get("user_id")
            if not self._login_token or not self._app_token or not self._user_id:
                raise AuthenticationError(code="incomplete-login-tokens")

    return DiagnosticSession(email, password)


def fetch_devices(session):
    import requests
    from huami_token.constants import HEADERS, URL_PARAMS
    from huami_token.models import Device

    params = URL_PARAMS.ZEPP_DEVICES.value.copy()
    params.update(userid=session.user_id, appid="2882303761517383915",
                  r=[str(uuid.uuid4())] * 2)
    headers = HEADERS.ZEPP_DEVICES.value.copy()
    headers.update(apptoken=session.app_token, appname="com.xiaomi.hm.health")
    headers["x-request-id"] = str(uuid.uuid4())
    # us3 was observed in this band's Zepp Life traffic and is documented by Gadgetbridge.
    for host in ("api-mifit-us3.zepp.com", "api-mifit.zepp.com"):
        response = requests.get(
            f"https://{host}/users/{quote(str(session.user_id), safe='')}/devices",
            params=params, headers=headers, timeout=30, allow_redirects=False,
        )
        print(f"{host}: HTTP {response.status_code}")
        if response.status_code != 200:
            continue
        try:
            data = response.json()
        except ValueError:
            print("Response was not JSON; contents withheld.")
            continue
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            print("Response lacked a device list; this does not establish that the account has no devices.")
            continue
        print(f"Device records: {len(items)}")
        if items:
            return [Device.from_api_response(item) for item in items]
    return []


def main():
    if not sys.stdin.isatty():
        raise SystemExit("Run this directly in an interactive terminal.")
    output = Path(__file__).resolve().parents[2] / "auth-key.txt"
    if output.exists():
        raise SystemExit("auth-key.txt already exists; check it locally before proceeding.")
    try:
        from loguru import logger
    except ImportError:
        raise SystemExit("Install the source version of huami-token in the dedicated environment first.")

    # Upstream debug logs can contain credentials and account tokens.
    logger.remove()
    configure_zepp_life()
    email, password = load_credentials(output.parent / ".env")
    session = make_session(email, password)
    stage = "login"
    logged_in = False
    try:
        print("Trying account login for Zepp Life (com.xiaomi.hm.health)...")
        session.login()
        logged_in = True
        stage = "device retrieval"
        devices = fetch_devices(session)
        if not devices:
            raise SystemExit("Login succeeded, but neither device lookup returned a usable list. No key saved.")
        for index, device in enumerate(devices, 1):
            print(f"{index}: {device.mac} (active: {device.active})")
        stage = "device selection"
        choice = int(input("Select the number matching your band's Bluetooth address: "))
        if not 1 <= choice <= len(devices):
            raise SystemExit("Invalid selection; no key saved.")
        key = devices[choice - 1].auth_key.removeprefix("0x")
        if not re.fullmatch(r"[0-9a-fA-F]{32}", key):
            raise SystemExit("Selected device did not return a valid 16-byte key.")
        stage = "saving the key"
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(key.lower() + "\n")
        print(f"Saved key privately to {output}. No band authentication has been tested yet.")
    except Exception as error:
        # Do not expose upstream exception text, which may include response data.
        code = getattr(error, "code", "")
        safe_code = code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_-]{1,64}", code) else "unavailable"
        raise SystemExit(f"Failed during {stage}: {type(error).__name__}; code: {safe_code}. No secrets printed.")
    finally:
        if logged_in:
            try:
                session.logout()
            except Exception:
                print("Account session logout failed; session tokens were not saved.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Cancelled.")
