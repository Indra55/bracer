import argparse
import asyncio
from contextlib import AsyncExitStack
import importlib.util
import json
import math
from pathlib import Path
import shutil
import socket
import sys
import time

from .approvals import ApprovalQueue
from .band import ConsoleBand
from .config import load_config, parse_auth_key, read_env, write_env
from .connection import ReconnectingBand
from .codex import CodexSession
from .service import ServiceBand, bluetooth_owner, default_socket, serve, service_status


def positive_seconds(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("Must be a finite positive number")
    return value


def parser():
    root = argparse.ArgumentParser(description="Bracer: Mi Band 5 command approvals for Codex")
    root.add_argument("--config", type=Path, default=Path(".env"))
    root.add_argument("--socket", type=Path, default=default_socket(), help="Local band service socket")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check dependencies and Bluetooth access")
    sub.add_parser("serve", help="Keep the band connected and serve local clients")
    sub.add_parser("status", help="Show background band service connection state")
    scan = sub.add_parser("scan", help="Find nearby bands")
    scan.add_argument("--seconds", type=positive_seconds, default=10)
    setup = sub.add_parser("setup", help="Save band address and existing pairing key locally")
    setup.add_argument("--address", required=True)
    setup.add_argument("--key-file", required=True, type=Path)
    probe = sub.add_parser("probe", help="Test real band text, vibration, and controls without Codex")
    probe.add_argument("--seconds", type=positive_seconds, default=120)
    demo = sub.add_parser("demo", help="Review a harmless local approval fixture; executes nothing")
    demo.add_argument("--simulate-band", action="store_true")
    demo.add_argument("--timeout", type=positive_seconds, default=180)
    run = sub.add_parser("run", help="Start a real Codex turn with approvals routed to the band")
    run.add_argument("prompt")
    run.add_argument("--cwd", type=Path, default=Path.cwd())
    run.add_argument("--resume", help="Resume a saved Codex thread; do not use an active thread")
    run.add_argument("--codex", default="codex", help="Path to Codex executable")
    run.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="workspace-write")
    run.add_argument("--simulate-band", action="store_true")
    run.add_argument("--timeout", type=positive_seconds, default=180)
    for command in (probe, demo, run):
        command.add_argument("--connect-timeout", type=positive_seconds, default=90,
                             help="Seconds to wait for the initial band connection")
    return root


def doctor():
    ok = True
    print(f"Python: {sys.version.split()[0]}")
    print(f"Codex: {shutil.which('codex') or 'MISSING'}")
    ok &= shutil.which("codex") is not None
    for module in ("bleak", "Crypto"):
        present = importlib.util.find_spec(module) is not None
        print(f"{module}: {'available' if present else 'MISSING; install requirements.txt'}")
        ok &= present
    if sys.platform.startswith("linux"):
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(2)
                connection.connect("/run/dbus/system_bus_socket")
            print("System D-Bus: accessible (adapter availability is checked by scan)")
        except OSError as error:
            print(f"System D-Bus: unavailable ({error}); run from your normal host terminal")
            ok = False
    return 0 if ok else 1


def save_config(args):
    key = parse_auth_key(args.key_file.read_text().strip()).hex()
    address = args.address.strip()
    if not address:
        raise ValueError("Band address cannot be empty")
    if args.config.suffix == ".json":
        raise ValueError("Save new configuration to .env; JSON is supported for legacy reads only")
    values = read_env(args.config) if args.config.exists() else {}
    values.update(MIBAND_ADDRESS=address, MIBAND_AUTH_KEY=key)
    write_env(args.config, values)
    print(f"Saved {args.config} with owner-only permissions. Pairing key is not printed.")


async def probe(band, seconds):
    print("Connected:", json.dumps(await band.info()))
    print("Open More > Music on the band. Confirm the text and vibration, then tap next, previous, play, and volume down.")
    required = {"next", "previous", "confirm", "deny"}
    seen = set()
    await band.show("Mi Band Codex test", "Connection test", "Next Prev Play Vol-")
    await band.vibrate()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            event = await asyncio.wait_for(band.events.get(), deadline - time.monotonic())
        except TimeoutError:
            break
        print("Band control:", event.action, flush=True)
        if event.action == "disconnect":
            raise RuntimeError("Band disconnected during test")
        if event.action == "open":
            await asyncio.sleep(0.1)
            await band.show("Mi Band Codex test", "Connection test", "Next Prev Play Vol-")
        if event.action in required:
            seen.add(event.action)
        if seen == required:
            print("All four input types received. Text readability and vibration still need your confirmation.")
            return 0
    print("Missing controls:", ", ".join(sorted(required - seen)))
    return 1


async def main(args):
    if args.command == "doctor":
        return doctor()
    if args.command == "setup":
        save_config(args)
        return 0
    if args.command == "serve":
        await serve(args.config, args.socket)
        return 0
    if args.command == "status":
        print(json.dumps(await service_status(args.socket)))
        return 0
    if args.command == "scan":
        from bleak import BleakScanner
        devices = await BleakScanner.discover(timeout=args.seconds, return_adv=True)
        for device, advertisement in devices.values():
            print(f"{device.address}  {advertisement.local_name or device.name or '(unnamed)'}")
        if not devices:
            print("No devices found. Turn off phone Bluetooth and wake the band before retrying.")
        return 0 if devices else 1
    async with AsyncExitStack() as stack:
        if getattr(args, "simulate_band", False):
            band = ConsoleBand()
        elif args.socket.exists():
            band = ServiceBand(args.socket)
        else:
            stack.enter_context(bluetooth_owner(args.socket))
            band = ReconnectingBand(*load_config(args.config))
        await stack.enter_async_context(band)
        if not getattr(args, "simulate_band", False):
            print("Waiting for band connection...", flush=True)
            await band.wait_connected(args.connect_timeout)
        if args.command == "probe":
            return await probe(band, args.seconds)
        if args.command == "demo":
            print("DEMO ONLY: no command will execute.", flush=True)
            answer = asyncio.get_running_loop().create_future()

            async def reply(_, result):
                answer.set_result(result)

            approvals = ApprovalQueue(band, reply, args.timeout)
            approvals.start()
            approvals.submit("demo", {"threadId": "demo", "turnId": "demo", "itemId": "demo",
                                      "command": "python3 --version", "cwd": str(Path.cwd())})
            try:
                print("Demo result:", await answer)
            finally:
                await approvals.close()
            return 0
        if not args.cwd.is_dir():
            raise ValueError("--cwd must be an existing directory")
        status = await CodexSession(band, args.timeout).run(
            args.prompt, args.cwd.resolve(), args.codex, args.sandbox, args.resume,
        )
        return 0 if status == "completed" else 1


def entrypoint():
    try:
        return asyncio.run(main(parser().parse_args()))
    except KeyboardInterrupt:
        print("\nStopped; no automatic approvals.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(entrypoint())
