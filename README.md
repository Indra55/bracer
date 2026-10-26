# bracer

![bracer and fitness-band illustration](docs/assets/bracer-header.svg)

Your coding agent wants to run a command. Your fitness tracker would like a word.

Bracer puts Codex command approvals on a **Mi Band 5**. Read the command on your wrist, tap play to let it run, or volume down to decline. Next/previous pages through the details.

Yes, the music screen. The artist, album, and track fields were sitting right there.

```text
  Codex ── permission hook ── local socket ── Bluetooth ── your wrist
                                                            │
                                                      play  → allow once
                                                      vol−  → decline
```

The computer talks straight to the band. Zepp Life gets involved for pairing and the initial key; after that, turn phone Bluetooth off so it releases the connection. The service keeps the band connected and queues reviews from multiple chats.

## give it a wrist

You'll need **Linux + BlueZ**, **Python 3.11+**, a paired **Mi Band 5**, and a logged-in **Codex CLI**.

The quick route: give your coding agent the [setup skill](skills/bracer-setup/SKILL.md).

```text
Set up Bracer using https://github.com/Indra55/bracer/blob/main/skills/bracer-setup/SKILL.md
```

Or [do it yourself](docs/SETUP.md). The pairing key stays in an ignored `.env`. You'll still need to trust the hook in Codex's `/hooks` menu.

Curious, but your band is in a drawer somewhere? Try the terminal version:

```sh
git clone https://github.com/Indra55/bracer.git
cd bracer
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m miband_agent demo --simulate-band
```

`n` / `p` to browse, `y` to approve, `d` to decline. This demo executes nothing.

## the slightly cursed bit

Bracer sends text through the band's music metadata protocol and listens for music-control events. Stock firmware, a BLE connection, and some Python. The [protocol notes](docs/DEVELOPMENT.md) have the wiring; the [key-retrieval notes](docs/AUTH_KEY.md) have the rabbit hole.

It follows Codex's existing permission rules. Play approves **one request**, without saving an allow rule. Losing the band during review declines the request. If the band is unavailable before review starts, Codex keeps its normal prompt. Other approval types stay in Codex.

## things that still need poking

Real standalone Codex commands have been accepted and rejected from the band. The ordinary-chat hook is implemented, but its complete accept/decline round trip still needs validation. Readability, vibration, and repeated reconnects need more time on actual hardware. [Receipts and loose ends →](docs/DEVICE_ACCEPTANCE.md)

---

[setup](docs/SETUP.md) · [commands / troubleshooting](docs/USAGE.md) · [internals](docs/DEVELOPMENT.md) · [experimental tools](docs/KEY_CAPTURE.md) · [AGPL-3.0-or-later](LICENSE)
