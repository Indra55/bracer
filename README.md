# Bracer

**Codex asks. Your wrist answers.**

Bracer turns a Mi Band 5 into a local command approval remote for Codex. A command that needs permission appears on the band's music screen. Browse its details, press play to approve it once, or volume down to decline. Your computer talks directly to the band over Bluetooth; the phone is needed for the initial pairing and key retrieval.

This is a working prototype. Earlier standalone sessions demonstrated real Codex command acceptance and rejection on hardware. The ordinary-chat hook is implemented and was discovered by Codex, but its trust step and a real ordinary-chat accept/decline test remain pending. Readability, vibration, repeated range recovery, and reboot startup also need physical validation. See [validation status](docs/DEVICE_ACCEPTANCE.md).

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install and configure](#install-and-configure)
- [Connect ordinary Codex chats](#connect-ordinary-codex-chats)
- [Controls and review behavior](#controls-and-review-behavior)
- [Commands](#commands)
- [Service management](#service-management)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [References and license](#references-and-license)

## How it works

```text
Local Codex chat
    │ PermissionRequest hook
    ▼
Bracer hook ── private Unix socket ── background service
                                          │ Bluetooth LE
                                          ▼
                                  Mi Band 5 music screen
                                          │ button decision
                                          ▼
                               allow once / deny request
```

The service owns one Bluetooth connection and queues requests from multiple chats. Each decision belongs to one request. It scans, authenticates, subscribes to controls, and reconnects after a connection loss. There is no firmware flashing, custom band app, phone relay, or Bracer cloud service.

The hook handles shell command permission requests matched as `Bash` by Codex. File changes, app/MCP confirmations, and questions use Codex's native flow. Bracer preserves Codex's sandbox, approval policy, and saved rules: commands already allowed by Codex can run without a band prompt. Local hooks do not extend to cloud Codex tasks or cloud-orchestrated Work sessions.

## Requirements

- Linux with BlueZ, a working Bluetooth LE adapter, and a systemd user session for background startup.
- Python 3.11 or newer.
- A Mi Band 5 already paired in Zepp Life, and its existing 16-byte authentication key.
- A logged-in Codex CLI with App Server and command-hook support. The integration was checked against CLI `0.164.0`; other versions have not been validated here.
- A normal host terminal with access to Bluetooth D-Bus. A restricted execution sandbox may block Bluetooth or Unix sockets.

Other band models and operating systems have not been validated. Firmware differences can affect the music screen and controls.

## Install and configure

Run commands from your checkout. The Python module remains `miband_agent` so existing commands and installed integrations stay compatible with the Bracer name.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m miband_agent doctor
cp .env.example .env
chmod 600 .env
```

### 1. Retrieve your existing pairing key

Keep the existing Zepp Life pairing. Obtain the band's 32-character hexadecimal key and save it in local `auth-key.txt` using an editor, then run `chmod 600 auth-key.txt`. Do not paste it into chat or shell history.

The browser-session method worked during this project's setup with a Google login. See [pairing-key setup](docs/AUTH_KEY.md) for that route, account/backend caveats, and key rotation. The earlier phone-proxy route failed on the tested phone; its helpers are retained as [experimental setup tools](docs/KEY_CAPTURE.md).

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

The hook keeps its existing display name to avoid changing the installed definition during this cleanup. It runs absolute paths to this checkout's Python environment and hook script, so keep the checkout in place. Reinstall after moving it, then review any changed definition in `/hooks`.

```sh
# Check discovery and trust status without starting an agent turn:
.venv/bin/python scripts/check_codex_hook.py

# Install only the Bluetooth service:
python3 scripts/install-linux.py --without-codex-hook

# Print the service unit without installing or starting anything:
python3 scripts/install-linux.py --dry-run
```

The dry run still requires an existing virtual environment and saved band configuration. To disable command routing, disable **Review command on Mi Band** in `/hooks`.

## Controls and review behavior

| Music control | Pending approval |
| --- | --- |
| Next track | Next page |
| Previous track | Previous page |
| Play / pause | Approve this request once, from any page |
| Volume down | Decline this request immediately |
| Volume up | No action |

The preview includes the command, working directory, reason, and supplied review context. Internal thread/item identifiers are omitted; command text is paginated without truncation. Unsupported glyphs and control characters are escaped. Headings show a request tag, page position, and time remaining when the page was rendered, rather than a live countdown. Long commands may need many pages; browsing every page is optional.

Requests appear one at a time. Inputs received before a page finishes sending are ignored. Leaving the music screen resets review to the first page. A disconnect, failed display write, or expired deadline declines submitted requests. Canceled chats withdraw their reviews. Approval never creates a saved allow rule or session-wide permission.

If the service is unavailable, offline, or busy with a standalone client before review starts, the hook leaves the normal Codex prompt available. Hook reviews have a 120-second deadline including queue time; the hook process timeout is 180 seconds. The transport cannot prove that text reached the physical display, so the probe and real device checks matter.

## Commands

Global options go **before** the subcommand:

```sh
.venv/bin/python -m miband_agent --config /path/to/.env --socket /private/path/bridge.sock status
.venv/bin/python -m miband_agent --help
.venv/bin/python -m miband_agent run --help
```

A custom socket's parent directory must be owned by you with mode `0700`. The normal socket uses `$XDG_RUNTIME_DIR/miband-agent/bridge.sock`, or `/tmp/miband-agent-UID/bridge.sock` when that variable is absent.

| Command | Purpose and options |
| --- | --- |
| `doctor` | Check Python, Codex, dependencies, and Linux D-Bus access |
| `scan` | List nearby BLE devices; `--seconds 10` |
| `setup` | Save address/key; `--address ADDRESS --key-file PATH` |
| `probe` | Test real display, vibration, and four controls; `--seconds 120` |
| `serve` | Run the reconnecting Bluetooth service in the foreground |
| `status` | Print service connection, busy state, pending count, and latest error as JSON |
| `demo` | Review a harmless fixture; executes no command; `--timeout 180`, optional `--simulate-band` |
| `run PROMPT` | Start an optional standalone Codex turn; options below |

`probe`, `demo`, and `run` accept `--connect-timeout 90` for the initial connection wait. `demo` and `run` accept `--timeout` for review deadlines. All durations must be finite positive numbers.

### Harmless demo

```sh
# Real band, no command execution:
.venv/bin/python -m miband_agent demo

# Explicit terminal simulation, no Bluetooth required:
.venv/bin/python -m miband_agent demo --simulate-band
```

Simulation accepts `n` (next), `p` (previous), `y` (approve), or `d` (decline), followed by Enter. Bluetooth failure never silently selects simulation.

### Optional standalone client

```sh
.venv/bin/python -m miband_agent run 'Inspect this project' --cwd /path/to/project
.venv/bin/python -m miband_agent run 'Continue' --cwd /path/to/project --resume THREAD_ID
```

`run` starts a separate real Codex App Server session and prints its thread ID. It accepts `--codex PATH`, `--sandbox read-only|workspace-write` (default `workspace-write`), `--timeout 180`, and `--simulate-band`. Simulation replaces only the band; **`run --simulate-band` still starts a real agent**. Resume an idle saved thread, not one already active elsewhere.

The standalone client uses `on-request` approvals, declines unsupported file-change approvals, and displays progress/completion updates when the band is available. It does not implement interactive question answering. Ctrl+C stops the client and its App Server process; commands already started are not rolled back.

## Service management

```sh
.venv/bin/python -m miband_agent status
systemctl --user status miband-agent.service
journalctl --user -u miband-agent.service -f
systemctl --user restart miband-agent.service
systemctl --user stop miband-agent.service
systemctl --user disable --now miband-agent.service
```

The service starts at login, reconnects to the band, and waits for requests. It never starts or resumes Codex tasks on its own. Reconnect delays increase from 1 to 30 seconds; scanning/authentication adds time. Requests and display writes from an old connection are invalidated and never replayed. The service keeps retrying after a client's initial connection wait times out.

`probe`, `demo`, and `run` use the service socket with exclusive control when present. Without a service, they connect directly with automatic retries. A local lock prevents simultaneous Bluetooth owners. `status` remains available while the band is busy. Clients try to reattach after a service restart.

For temporary phone use, stop the service, then enable phone Bluetooth. Release the phone connection before restarting Bracer. After changing the pairing key, rerun `setup` and restart the service so it loads the new value.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Band not found | Wake it, move it closer, turn off phone Bluetooth, and retry `scan` |
| Bluetooth powered off | Enable the adapter; inspect `status` and the service journal |
| Authentication rejected | Verify the model/key; unbinding or re-pairing requires the new key and a service restart |
| Waiting for band connection | `status` reports the latest failure; `--connect-timeout` changes the initial wait |
| `Request Not Supported` | Preserve the full error and characteristic/write mode; this alone does not establish a bad key |
| Controls missing | Open More → Music and run `probe`; record the firmware and missing controls |
| Normal Codex prompt appears | Check hook trust, restart Codex, then check service connection and busy state |
| Hook is not discovered | Run `check_codex_hook.py`; confirm Codex supports hooks and the checkout paths still exist |
| Another bridge owns Bluetooth | Use the existing service, or stop it before making a direct connection |
| Service socket is stale | Restart `miband-agent.service` and inspect its journal |
| Phone no longer connects | Stop Bracer before reconnecting Zepp Life |

Do not unbind or factory reset as a generic reconnect fix. That changes the pairing key. See [pairing-key setup](docs/AUTH_KEY.md).

## Development

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Tests cover authentication/framing, complete pagination, request scoping, stale inputs, timeout/cancellation, connection generations, service ownership/reconnection, hook output/fallback, installer preservation/idempotence, and a fake Codex subprocess. A real Unix-socket integration test runs where the host permits sockets. These checks do not replace physical band or provider-backed acceptance tests.

```text
miband_agent/
  __main__.py       CLI, setup, probe, demo
  config.py         private .env I/O and legacy configuration reader
  band.py           Bluetooth authentication, display framing, console simulation
  connection.py     reconnect supervision and connection generations
  approvals.py      queued review and per-request decisions
  service.py        one Bluetooth owner and local socket clients
  hook.py           native Codex permission-hook adapter
  codex.py          optional standalone App Server client
scripts/
  install-linux.py  user service and hook installation
  check_codex_hook.py
  codex_approval_hook.py
  experimental/     optional key-retrieval and APK-inspection helpers
tests/             automated protocol, service, hook, and configuration checks
docs/              key setup, experiment limitations, device acceptance
```

Local `.tools/`, `.capture-venv/`, and `.capture-ca/` directories are ignored remnants of setup experiments, not runtime dependencies. The regular `.venv/` is the runtime environment. Never commit pairing keys, account credentials, proxy private keys, or captured traffic.

## References and license

- [Codex App Server](https://learn.chatgpt.com/docs/app-server) and [hooks](https://learn.chatgpt.com/docs/hooks): request/decision protocol and hook trust.
- [Gadgetbridge Huami support](https://github.com/Freeyourgadget/Gadgetbridge/blob/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huami/HuamiSupport.java), [service constants](https://github.com/Freeyourgadget/Gadgetbridge/blob/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huami/HuamiService.java), and [initialization](https://github.com/Freeyourgadget/Gadgetbridge/blob/master/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huami/operations/init/InitOperation.java): protocol references. Contributors include Andreas Shimokawa and José Rebelo.
- [Mi Band 5 external live data](https://github.com/robtacconelli/Mi-Band-5-Show-External-Live-Data): precedent for displaying custom text through the music screen; its Android code is not included here.
- [Bleak](https://bleak.readthedocs.io/en/latest/api/client.html): Bluetooth transport.

AGPL-3.0-or-later. See [LICENSE](LICENSE).
