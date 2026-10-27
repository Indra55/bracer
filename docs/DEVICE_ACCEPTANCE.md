# Validation status

Software checks, historical hardware results, and current physical acceptance are separate. This page records dated observations through 2026-10-27; it does not assert that an installed service or device is currently connected.

## Reconnect investigation, 2026-10-27

- The enabled service started at login but repeatedly reported `Band not found`, even while BlueZ reported the configured band connected. The phone's Bluetooth had also been on; the user turned it off.
- Fixed discovery to reuse an existing BlueZ connection to the configured address before scanning for advertisements. Restarting the service then immediately logged `Band connected; controls ready`.
- Codex CLI `0.164.0` reported the global PermissionRequest hook enabled and **trusted**.
- An ordinary chat's real host status command reached the band; the user confirmed seeing the approval, and the service logged `Approval 454d: accept` at 23:01:12 IST. Codex then executed the command, which returned `connected: true`, `pending_reviews: 0`, and `error: null`. This confirms ordinary-chat acceptance with the current service. Ordinary-chat rejection remains unverified.
- The updated suite ran 69 tests: 68 passed and the real Unix-socket test was skipped because the executor blocks sockets. Regression checks cover an already-connected band without advertising, scanning when no connection exists, matching the configured address, and closing the D-Bus connection on errors.

## Automated checks

The cleanup suite passed all 66 tests, including the real Unix-socket integration test, with temporary-file/socket access enabled. The pre-cleanup baseline also passed all 56 original tests. Coverage includes:

- Known-vector AES authentication, supported GATT write modes, protocol framing, and event decoding.
- Complete command pagination, immediate one-request approval, optional navigation, stale inputs, expiry, cancellation, display failures, and queued requests.
- Reconnect generations, absent-band startup, no replay of old writes/approvals, one service owner, and client reattachment.
- Hook input/output, JSON-only stdout, offline/busy fallback, concurrent chats, and preserving/idempotently updating other hooks.
- A fake Codex subprocess, plus a real local socket with a fake Bluetooth transport.

Configuration migration tests additionally cover `.env` quoting, literal shell expressions, owner-only writes, preservation of account entries, malformed input, and legacy JSON reading. These tests do not access the real band or start a provider-backed agent.

The updated user service was installed, verified enabled/active, and returned status through its real Unix socket after migration to `.env`. Its initial status was disconnected; no new physical Bluetooth acceptance result is claimed. Dependency consistency (`pip check`) and CLI/installer dry-run checks also passed.

## Historical device evidence

- [x] Host discovery/authentication and all four required probe controls were reported working.
- [x] A real-band demo returned `accept`; it executed no command.
- [x] A standalone provider-backed Codex run accepted a band decision and completed `touch approved.txt`. The previously absent empty marker was independently checked.
- [x] A later standalone run declined that command. Codex reported user rejection, and the existing marker's timestamps stayed unchanged.
- [x] After re-pairing, the updated key recovered a connection: the service logged `Band connected; controls ready` on 2026-10-26, and the user reported the demo worked.
- [x] The user service had been installed/enabled; the generated unit passed host verification.
- [x] Codex CLI `0.164.0` discovered the global hook as enabled and **untrusted**.

The standalone acceptance/rejection results preceded later reconnect and native-hook changes. They establish the earlier real path, not completed physical regression of the current version. The failed proxy capture retrieved no key; the browser-session route later did.

## Remaining physical acceptance

- [ ] Confirm probe text readability and actual vibration.
- [ ] Confirm device model/firmware directly; the successful probe returned no model/firmware strings.
- [ ] Review a long command across all pages on the physical display.
- [ ] Verify immediate first-page acceptance and deliberate rejection using the current service.
- [ ] Verify timeout and disconnect decline pending requests on hardware.
- [ ] Verify automatic recovery after range loss and a band restart.
- [ ] Verify login startup after an actual computer reboot.
- [x] Confirm trusted hook discovery and ordinary-chat acceptance without `run` (2026-10-27).
- [ ] Confirm ordinary-chat rejection without `run`.
- [ ] Confirm readable standalone progress updates and completion vibration.

## Reproduce

Run the software suite with `.venv/bin/python -m unittest discover -s tests -v`. Run `probe`, then `demo`, from a normal Bluetooth-capable host terminal. For ordinary chats, follow the [hook setup](SETUP.md#connect-ordinary-codex-chats) and trigger a command that genuinely needs permission. Record command completion for acceptance and explicit rejection/non-execution for decline; a discovered hook alone does not establish that it ran.
