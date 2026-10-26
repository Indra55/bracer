# Setup

Install Bracer, connect your band, and enable command approvals in local Codex chats. Run the commands from the checkout directory.

For agent-assisted setup, share the [setup skill](../skills/bracer-setup/SKILL.md) with your coding agent:

```text
Set up Bracer using https://github.com/Indra55/bracer/blob/main/skills/bracer-setup/SKILL.md
```

The skill reuses existing configuration and guides the agent through installation and checks. Pairing-key retrieval, physical controls, and Codex hook trust can still require your input.

## Requirements

- Linux with BlueZ, a working Bluetooth LE adapter, and a systemd user session for background startup.
- Python 3.11 or newer.
- A Mi Band 5 already paired in Zepp Life, and its existing 16-byte authentication key.
- A logged-in Codex CLI with App Server and command-hook support. The integration was checked against CLI `0.164.0`; other versions have not been validated here.
- A normal host terminal with access to Bluetooth D-Bus. A restricted execution sandbox may block Bluetooth or Unix sockets.

Other band models and operating systems have not been validated. Firmware differences can affect the music screen and controls.

## Install and configure

Bracer uses the Python module `miband_agent`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m miband_agent doctor
cp .env.example .env
chmod 600 .env
```

### 1. Retrieve your existing pairing key

Keep the existing Zepp Life pairing. Obtain the band's 32-character hexadecimal key and save it in local `auth-key.txt` using an editor, then run `chmod 600 auth-key.txt`. Do not paste it into chat or shell history.

The browser-session method worked during this project's setup with a Google login. See [pairing-key setup](AUTH_KEY.md) for that route, account/backend caveats, and key rotation. The earlier phone-proxy route failed on the tested phone; its helpers are retained as [experimental setup tools](KEY_CAPTURE.md).

### 2. Connect and save configuration

Turn off the phone's Bluetooth so Zepp Life releases the band. Wake the band and keep it near your computer. Do not unbind or factory reset it.

```sh
.venv/bin/python -m miband_agent scan
.venv/bin/python -m miband_agent setup --address AA:BB:CC:DD:EE:FF --key-file auth-key.txt
.venv/bin/python -m miband_agent probe
```

Replace the example address with your band's address. `setup` writes `MIBAND_ADDRESS` and `MIBAND_AUTH_KEY` to `.env` atomically with mode `0600`, preserving other entries. After setup, delete the extra `auth-key.txt` copy if you no longer need it.

Open **More → Music** during `probe`. Confirm the displayed text and vibration, then tap next, previous, play/pause, and volume down. The probe succeeds after receiving all four input types; you must assess readability and vibration yourself.

### Private configuration

| Entry | Used by |
| --- | --- |
| `MIBAND_ADDRESS` | Band discovery and connection |
| `MIBAND_AUTH_KEY` | Bluetooth authentication; 32 hexadecimal characters |
| `ZEPP_EMAIL` | Optional experimental account-key helper |
| `ZEPP_PASSWORD` | Optional experimental account-key helper |

`.env` is ignored by Git; `.env.example` contains placeholders only. Entries use `NAME=value` with shell-style quotes for spaces or special characters. The reader does not execute shell substitutions or expand variables. It reads the selected file rather than loading values into the process environment. Keep it owner-only with `chmod 600 .env`.

The default configuration path is `.env` relative to the current directory. Use `--config /absolute/path/.env` before the subcommand when running elsewhere. Explicit legacy `.json` configurations remain readable with `--config`; new setups should use `.env`. The installer uses an absolute configuration path.

## Connect ordinary Codex chats

Install the background service and hook once:

```sh
python3 scripts/install-linux.py
```

The installer starts and enables `miband-agent.service` at login, adds the command handler to `~/.codex/hooks.json` (or `CODEX_HOME`), preserves other hooks, and backs up an existing hook file before updating it. It also asks Codex to discover the hook. Installation does not grant hook trust.

1. Open Codex and enter `/hooks`.
2. Review and trust **Review command on Mi Band**.
3. Restart Codex, then open or resume your local chats normally.
4. Trigger a command that actually requires permission and verify both approval and rejection from the band.

The hook is named **Review command on Mi Band** in Codex. It runs absolute paths to this checkout's Python environment and hook script, so keep the checkout in place. Reinstall after moving it, then review any changed definition in `/hooks`.

```sh
# Check discovery and trust status without starting an agent turn:
.venv/bin/python scripts/check_codex_hook.py

# Install only the Bluetooth service:
python3 scripts/install-linux.py --without-codex-hook

# Print the service unit without installing or starting anything:
python3 scripts/install-linux.py --dry-run
```

The dry run still requires an existing virtual environment and saved band configuration. To disable command routing, disable **Review command on Mi Band** in `/hooks`.

Next: [controls, commands, and troubleshooting](USAGE.md).
