# Bracer

**Codex asks. Your wrist answers.**

Review Codex command approvals on a Mi Band 5. Read the command on its music screen, press play to approve once, or volume down to decline.

Bracer connects directly over Bluetooth, queues requests from local chats, and reconnects when the band returns. Your phone is only needed for pairing and key retrieval.

## Get started

You'll need Linux, Python 3.11+, a Bluetooth LE adapter, a paired Mi Band 5, and a logged-in Codex CLI. Run from the checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Using a coding agent? Point it at the [Bracer setup skill](skills/bracer-setup/SKILL.md).

Follow the [setup guide](docs/SETUP.md) to retrieve your pairing key, connect the band, and install the Codex hook. Private configuration stays in an ignored `.env`.

To try the review flow in your terminal without a band or command execution:

```sh
.venv/bin/python -m miband_agent demo --simulate-band
```

## Controls

Open **More → Music** on the band when a review arrives.

| Control | Action |
| --- | --- |
| Play / pause | Approve once |
| Volume down | Decline |
| Next / previous track | Browse command details |

Bracer follows Codex's existing approval policy. It routes shell command requests; other approval types stay in Codex. If the band is unavailable before review starts, the normal prompt remains available.

## Documentation

- [Setup](docs/SETUP.md): installation, private configuration, and hook trust
- [Usage](docs/USAGE.md): commands, service management, and troubleshooting
- [Pairing keys](docs/AUTH_KEY.md): retrieval and rotation
- [Development](docs/DEVELOPMENT.md): architecture, tests, and protocol references
- [Validation](docs/DEVICE_ACCEPTANCE.md): hardware evidence and remaining checks
- [Experimental tools](docs/KEY_CAPTURE.md): optional setup helpers and their limitations

**Prototype status:** real standalone approvals and rejections have worked on hardware. Ordinary-chat hook validation and further physical checks remain pending; see [validation](docs/DEVICE_ACCEPTANCE.md).

[AGPL-3.0-or-later](LICENSE).
