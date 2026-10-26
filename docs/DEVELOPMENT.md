# Development

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

## Checks and source layout

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

AGPL-3.0-or-later. See [LICENSE](../LICENSE).
