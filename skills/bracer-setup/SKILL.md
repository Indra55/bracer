---
name: bracer-setup
description: Set up or reconnect Bracer, the Mi Band 5 command approval remote for local Codex chats, including private configuration, Bluetooth checks, and the user service and hook.
---

# Bracer setup

Get the user's band connected and ordinary local Codex chats ready for wrist approvals. Reuse working configuration and report the next concrete step if hardware, credentials, or hook trust blocks completion.

## Find the checkout

Use an existing Bracer checkout when available: it contains `miband_agent/`, `scripts/install-linux.py`, and `requirements.txt`. Otherwise clone `https://github.com/Indra55/bracer.git` into the user's workspace. Keep this location stable; installed hooks and the service use absolute checkout paths. Run the following commands from that checkout, even if this skill was installed elsewhere.

Read `docs/SETUP.md` in the checkout for configuration or installer details. Read `docs/USAGE.md` only for a relevant failure or an explicitly requested standalone client. The Python module and service are named `miband_agent` and `miband-agent.service`.

## Prepare the host

Bracer targets Linux with BlueZ, Bluetooth LE, Python 3.11+, a logged-in Codex CLI, and a systemd user session. Mi Band 5 is the validated model; don't promise other models or platforms work. CLI `0.164.0` was checked during development; use the installed CLI's help when troubleshooting version differences.

Reuse `.venv` if present; create it otherwise. Install the pinned requirements there, then check the host:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m miband_agent doctor
```

Skip the venv creation command when reusing it. Address failed doctor checks before attempting Bluetooth setup. If the agent's sandbox blocks system D-Bus, use the available execution approval mechanism or give the user the precise host-terminal command. Don't treat blocked sandbox access as a broken adapter.

## Reuse or configure the pairing

If `.env` already exists, validate it without printing its values:

```sh
.venv/bin/python -c 'from miband_agent.config import load_config; load_config(".env"); print("Band configuration valid")'
```

Preserve an existing `.env`, its account entries, and other local configuration. Never print or request pairing keys, passwords, or browser tokens in chat. Keep `.env` ignored and mode `0600`; don't source it as shell code. A valid saved key can still be stale after re-pairing.

For first setup, ask for the path to a private local key file and the band's address if they are not already available. Use `docs/AUTH_KEY.md` for retrieval guidance when needed. The browser route worked during development, but the exact successful snippet was not retained. Don't invent account API requests or start the experimental proxy/account tools by default. Preserve the existing Zepp Life pairing; unbinding or factory resetting invalidates the old key.

```sh
.venv/bin/python -m miband_agent scan
.venv/bin/python -m miband_agent setup --address BAND_ADDRESS --key-file /path/to/private-key.txt
```

Substitute the actual address and existing private file path; `setup` writes `.env` privately and preserves other entries. Offer to remove a redundant key-file copy after successful import; don't remove a user-owned file automatically.

## Check the band

Have the user turn off phone Bluetooth, wake the band, and open **More → Music**. Check `status` first if a service is already installed; don't launch a second Bluetooth owner. The probe attaches to the service when available:

```sh
.venv/bin/python -m miband_agent probe --seconds 45 --connect-timeout 30
```

Ask the user to press next, previous, play/pause, and volume down during the probe. Receiving four controls proves input delivery; only the user can confirm readable text and vibration. If the band is absent or authentication fails, inspect the reported stage and stop repeated manual attempts until the phone connection, range, adapter, or key issue changes. The background service already retries automatically. Never reset the band as a reconnect fix.

## Install the ordinary-chat integration

For the requested full setup:

```sh
python3 scripts/install-linux.py
.venv/bin/python -m miband_agent status
.venv/bin/python scripts/check_codex_hook.py
```

The installer preserves other Codex hooks, backs up changes to `hooks.json`, and enables the user service. For a service-only request, use `--without-codex-hook`. Don't change global sandbox or approval policy to manufacture prompts. After changing the key, restart the service so it reads the new `.env`.

The user must open Codex `/hooks`, review/trust **Review command on Mi Band**, and restart Codex. Don't edit trust state to bypass this review. An enabled/discovered hook can still be untrusted. Report that exact next action when trust is pending; don't reinstall a healthy integration in a loop.

## Verify and hand off

An optional `.venv/bin/python -m miband_agent demo` checks band decisions without executing a command. `demo --simulate-band` checks only terminal simulation. The `run` command starts a separate real agent, including with `--simulate-band`; don't use it as an installation smoke test.

Report separately what was verified: configuration, service health, Bluetooth connection, control inputs, hook discovery/trust, and a real ordinary-chat round trip. A running service does not establish a connected band. Don't claim ordinary-chat success until a command that genuinely needs permission has been accepted and a separate request declined through that chat. If the user wants that final check, coordinate a harmless test and observe the command outcomes.

Finish with what works and the next manual step, if any. Don't update the project's historical acceptance checklist based on an unobserved result.
