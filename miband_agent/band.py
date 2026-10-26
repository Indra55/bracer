import asyncio
import time
from dataclasses import dataclass


AUTH = "00000009-0000-3512-2118-0009af100700"
EVENT = "00000010-0000-3512-2118-0009af100700"
CHUNKED = "00000020-0000-3512-2118-0009af100700"
ALERT = "00002a06-0000-1000-8000-00805f9b34fb"
MODEL = "00002a24-0000-1000-8000-00805f9b34fb"
FIRMWARE = "00002a26-0000-1000-8000-00805f9b34fb"
MUSIC_EVENTS = {
    0: "confirm", 1: "confirm", 3: "next", 4: "previous",
    5: "volume_up", 6: "deny", 224: "open", 225: "close",
}


@dataclass(frozen=True)
class BandEvent:
    action: str
    at: float


def music_event(data):
    if len(data) == 2 and data[0] == 0xFE:
        return MUSIC_EVENTS.get(data[1])
    return None


def music_payload(text, heading, hint):
    fields = [heading, hint, text]  # artist, album, track
    if any("\0" in value or len(value.encode("utf-8")) > 80 for value in fields):
        raise ValueError("Music fields must fit in 80 UTF-8 bytes without NULs")
    return b"\x0f\x01\x00\x00\x00" + b"".join(
        value.encode("utf-8") + b"\0" for value in fields
    )


def music_chunks(payload):
    # Classic Huami type-3 framing, using the minimum ATT MTU (23).
    for index, offset in enumerate(range(0, len(payload), 17)):
        last = offset + 17 >= len(payload)
        flags = (0x80 if last else 0) | (0x40 if (last and index == 0) or (not last and index > 0) else 0)
        yield bytes([0, flags | 3, index]) + payload[offset:offset + 17]


class Band:
    def __init__(self, address, key):
        self.address, self.key = address, key
        self.events = asyncio.Queue()
        self.client = None
        self._write_lock = asyncio.Lock()

    @property
    def connected(self):
        return bool(self.client and self.client.is_connected)

    def _disconnected(self, _):
        self.events.put_nowait(BandEvent("disconnect", time.monotonic()))

    def _event(self, _, data):
        action = music_event(data)
        if action:
            self.events.put_nowait(BandEvent(action, time.monotonic()))

    async def __aenter__(self):
        from bleak import BleakClient, BleakScanner
        device = await BleakScanner.find_device_by_address(self.address, timeout=20)
        if device is None:
            raise RuntimeError("Band not found. Turn off phone Bluetooth, wake the band, and retry.")
        self.client = BleakClient(device, disconnected_callback=self._disconnected)
        stage = "connecting and discovering services"
        try:
            await self.client.connect()
            for uuid in (AUTH, EVENT, CHUNKED):
                if self.client.services.get_characteristic(uuid) is None:
                    raise RuntimeError("This device does not expose the Mi Band 5 protocol")
            stage = "authenticating"
            await self._authenticate()
            stage = f"subscribing to music controls ({EVENT})"
            await self.client.start_notify(EVENT, self._event)
        except BaseException as error:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            if isinstance(error, Exception):
                raise RuntimeError(f"Band failed while {stage}: {error}") from error
            raise
        return self

    async def __aexit__(self, *_):
        if self.connected:
            await self.client.disconnect()

    async def _authenticate(self):
        from Crypto.Cipher import AES
        received = asyncio.Queue()
        try:
            await self.client.start_notify(AUTH, lambda _, data: received.put_nowait(bytes(data)))
        except Exception as error:
            raise RuntimeError(f"Cannot subscribe to authentication ({AUTH}): {error}") from error
        # Keep auth notifications active until disconnect, as in Gadgetbridge's init flow.
        async with asyncio.timeout(15):
            await self._write(AUTH, b"\x82\x00\x02\x01\x00")
            challenge = await received.get()
            if len(challenge) != 19 or challenge[0] != 0x10 or (challenge[1] & 0x0F) != 2 or challenge[2] != 1:
                raise RuntimeError(f"Band authentication challenge rejected or malformed "
                                   f"(header={challenge[:3].hex(' ')}, length={len(challenge)})")
            encrypted = AES.new(self.key, AES.MODE_ECB).encrypt(challenge[3:])
            await self._write(AUTH, b"\x83\x00" + encrypted)
            result = await received.get()
            if len(result) < 3 or result[0] != 0x10 or (result[1] & 0x0F) != 3 or result[2] != 1:
                raise RuntimeError(f"Band authentication failed "
                                   f"(header={result[:3].hex(' ')}, length={len(result)}); "
                                   "verify the pairing key and device model")

    async def _write(self, uuid, data, *, response=True):
        characteristic = self.client.services.get_characteristic(uuid)
        if characteristic is None:
            raise RuntimeError(f"Band characteristic is missing: {uuid}")
        properties = characteristic.properties
        preferred = "write" if response else "write-without-response"
        alternative = "write-without-response" if response else "write"
        if preferred not in properties:
            if alternative not in properties:
                raise RuntimeError(f"Band characteristic {uuid} is not writable (properties: {properties})")
            response = not response
        try:
            await self.client.write_gatt_char(uuid, data, response=response)
        except Exception as error:
            mode = "with response" if response else "without response"
            raise RuntimeError(f"Write {mode} to {uuid} failed (properties: {properties}): {error}") from error

    async def show(self, text, heading="Codex", hint="Next/Prev | Vol- NO"):
        async with self._write_lock:
            for chunk in music_chunks(music_payload(text, heading, hint)):
                await self._write(CHUNKED, chunk, response=False)
                await asyncio.sleep(0.02)

    async def vibrate(self):
        await self._write(ALERT, b"\x03")
        try:
            await asyncio.sleep(0.3)
        finally:
            if self.connected:
                await self._write(ALERT, b"\x00")

    async def info(self):
        result = {}
        for label, uuid in (("model", MODEL), ("firmware", FIRMWARE)):
            if self.client.services.get_characteristic(uuid):
                try:
                    raw = await self.client.read_gatt_char(uuid)
                except Exception as error:
                    raise RuntimeError(f"Cannot read band {label} ({uuid}): {error}") from error
                result[label] = bytes(raw).decode("utf-8", "replace").rstrip("\0")
        return result


class ConsoleBand:
    """Explicit simulator; never used as a fallback for a failed BLE connection."""

    def __init__(self):
        self.events = asyncio.Queue()
        self.connected = True
        self._loop = None

    async def __aenter__(self):
        import sys
        self._loop = asyncio.get_running_loop()

        def read():
            line = sys.stdin.readline()
            if not line:
                self.connected = False
                self._loop.remove_reader(sys.stdin.fileno())
                action = "disconnect"
            else:
                action = {"n": "next", "p": "previous", "y": "confirm", "d": "deny", "o": "open"}.get(line.strip())
            if action:
                self.events.put_nowait(BandEvent(action, time.monotonic()))

        self._loop.add_reader(sys.stdin.fileno(), read)
        print("SIMULATED BAND: n=next, p=previous, y=play, d=deny; then Enter", flush=True)
        return self

    async def __aexit__(self, *_):
        import sys
        self._loop.remove_reader(sys.stdin.fileno())
        self.connected = False

    async def show(self, text, heading="Codex", hint="Next/Prev | Vol- NO"):
        print(f"\n[BAND] {heading}\n{text}\n{hint}", flush=True)

    async def vibrate(self):
        print("[BAND] buzz", flush=True)
