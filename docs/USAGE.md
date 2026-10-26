# Usage

[Set up the band and hook](SETUP.md) first. For ordinary chats, use Codex normally: commands that require permission are sent to the band.

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

Do not unbind or factory reset as a generic reconnect fix. That changes the pairing key. See [pairing-key setup](AUTH_KEY.md).
