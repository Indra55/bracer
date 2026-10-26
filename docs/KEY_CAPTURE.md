# Experimental setup tools

These helpers are separate from Bracer's runtime. The browser route in [pairing-key setup](AUTH_KEY.md) succeeded during the original setup; the phone proxy and password-account attempts did not retrieve the key on that setup. Their optional dependencies are not in `requirements.txt`.

## Phone proxy: `scripts/experimental/capture_key.py`

A mitmproxy addon that extracts a key only from a matching Bluetooth address on device endpoints under Huami, Zepp, Amazfit, or Xiaomi domains. It handles `additionalInfo` JSON, rejects conflicting keys, writes mode `0600`, refuses to overwrite, and does not print key values or save full traffic. Its extraction and file behavior have synthetic tests.

The tested Android Zepp Life app rejected the proxy CA with `certificate unknown`. Repeating networking setup does not fix that trust rejection. A phone browser accepting the CA does not establish that Zepp Life will. No successful physical proxy capture is claimed.

For a separate compatible setup, install mitmproxy in its own environment and supply your own address:

```sh
python3 -m venv .capture-venv
.capture-venv/bin/python -m pip install mitmproxy
MIBAND_ADDRESS=AA:BB:CC:DD:EE:FF .capture-venv/bin/mitmdump \
  --listen-host 127.0.0.1 --listen-port 8082 \
  --set confdir=.capture-ca --set flow_detail=0 \
  --set 'allow_hosts=(^|\.)((huami|zepp|amazfit|xiaomi)\.com|mitm\.it)(:[0-9]+)?$' \
  -s scripts/experimental/capture_key.py
```

For an authorized Android USB-debugging connection, `adb reverse tcp:8082 tcp:8082` forwards the phone's localhost port to this listener. Configure the phone proxy at `127.0.0.1:8082`, install the temporary CA from `http://mitm.it`, and refresh Zepp Life only if that app supports the setup. Stop on certificate rejection.

Afterward stop the proxy, restore the phone proxy to None, remove its temporary CA, and run `adb reverse --remove tcp:8082`. Local `.capture-ca/` contains sensitive proxy material and must remain ignored. A successful extraction creates `auth-key.txt`; import it with the normal `setup` command and remove the spare copy.

## Account helper: `scripts/experimental/fetch_account_key.py`

An interactive diagnostic wrapper around the **source version** of [argrento/huami-token](https://github.com/argrento/huami-token). It needs that package and its dependencies in a separate environment. It is not installed by the Bracer runtime requirements, and its third-party internals/backend compatibility are not guaranteed.

It reads optional `ZEPP_EMAIL` and `ZEPP_PASSWORD` from the checkout's `.env` (which must be owner-only), otherwise prompts interactively. It requests Zepp Life sessions/device records, lets you select a matching address, suppresses upstream secret-bearing logs, and writes an exclusive mode-`0600` `auth-key.txt`. The account session is logged out when possible. Run with that environment's Python from an interactive terminal; it refuses noninteractive input and an existing output file.

## APK inspection: `scripts/experimental/export_zepp_apk.py`

Copies the installed Zepp Life base/split APKs for offline inspection using the existing ignored `.tools/platform-tools/adb` binary:

```sh
python3 scripts/experimental/export_zepp_apk.py --serial YOUR_ADB_SERIAL
```

The phone must authorize ADB and have `com.xiaomi.hm.health` installed. Output goes to ignored `.tools/zepp-apk/`. This copies app installers; it does not extract private app data or retrieve the pairing key. ADB and the APKs are not runtime dependencies.

## References

- [Android certificate trust](https://developer.android.com/privacy-and-security/security-config)
- [Mitmproxy certificates](https://docs.mitmproxy.org/stable/concepts/certificates/)
- [Android local-server access and reverse forwarding](https://developer.android.com/develop/ui/views/layout/webapps/access-local-server)
- [Mi Band key-capture precedent](https://github.com/Erencv/miband5-ble)
