"""Reconnect the band without replaying requests or display writes."""

import asyncio
import time

from .band import Band, BandEvent


class ReconnectingBand:
    def __init__(self, address, key, *, factory=Band, retry_min=1, retry_max=30):
        self.address, self.key = address, key
        self.factory = factory
        self.retry_min, self.retry_max = retry_min, retry_max
        self.events = asyncio.Queue()
        self.generation = 0
        self.last_error = None
        self._band = None
        self._ready = asyncio.Event()
        self._lost = asyncio.Event()
        self._lock = asyncio.Lock()
        self._task = None

    @property
    def connected(self):
        return bool(self._ready.is_set() and self._band and self._band.connected)

    async def __aenter__(self):
        self._task = asyncio.create_task(self._supervise())
        return self

    async def __aexit__(self, *_):
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

    async def wait_connected(self, timeout=90):
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except TimeoutError:
            raise ConnectionError("Band is still unavailable; check phone Bluetooth, range, and service logs") from None

    def _unavailable(self):
        if self._ready.is_set():
            if self.last_error is None:
                self.last_error = "Disconnected"
            self._ready.clear()
            self.generation += 1
            self.events.put_nowait(BandEvent("disconnect", time.monotonic()))
        self._lost.set()

    async def _forward(self, band):
        while True:
            event = await band.events.get()
            if event.action == "disconnect":
                self._unavailable()
                return
            if self.connected:
                self.events.put_nowait(event)

    async def _supervise(self):
        delay = self.retry_min
        while True:
            band = self.factory(self.address, self.key)
            forward = None
            try:
                self._lost.clear()
                async with asyncio.timeout(60):
                    await band.__aenter__()
                    # Clear any old approval screen before exposing the new connection.
                    await band.show("Ready for requests", "Codex connected", "No approval active")
                if not band.connected:
                    raise ConnectionError("Band disconnected during initialization")
                while not band.events.empty():
                    band.events.get_nowait()
                self._band = band
                self.generation += 1
                self.last_error = None
                self._ready.set()
                self.events.put_nowait(BandEvent("connected", time.monotonic()))
                print("Band connected; controls ready.", flush=True)
                delay = self.retry_min
                forward = asyncio.create_task(self._forward(band))
                await self._lost.wait()
                print(f"Band disconnected; reconnecting in {delay:g}s.", flush=True)
            except Exception as error:
                reason = getattr(getattr(error, "reason", None), "name", None)
                detail = str(error).replace(self.key.hex(), "<redacted>").replace(self.key.hex().upper(), "<redacted>")
                self.last_error = type(error).__name__ + (f": {reason}" if reason else "") + f": {detail[:400]}"
                print(f"Band unavailable ({self.last_error}); retrying in {delay:g}s.", flush=True)
                self.events.put_nowait(BandEvent("connection_error", time.monotonic()))
            finally:
                self._unavailable()
                if forward:
                    forward.cancel()
                    await asyncio.gather(forward, return_exceptions=True)
                self._band = None
                try:
                    await asyncio.wait_for(band.__aexit__(), 5)
                except Exception:
                    pass
            await asyncio.sleep(delay)
            delay = min(self.retry_max, delay * 2)

    async def _call(self, method, *args):
        generation = self.generation
        async with self._lock:
            if not self.connected or generation != self.generation:
                raise ConnectionError("Band disconnected; reconnecting automatically")
            band = self._band
            try:
                async with asyncio.timeout(15):
                    result = await getattr(band, method)(*args)
                if not self.connected or generation != self.generation:
                    raise ConnectionError("Band connection changed during operation")
                return result
            except Exception as error:
                if band is self._band:
                    self.last_error = f"Band {method} failed"
                    self._unavailable()
                raise ConnectionError(f"Band {method} failed; reconnecting automatically") from error

    async def show(self, text, heading="Codex", hint="Next/Prev | Vol- NO"):
        await self._call("show", text, heading, hint)

    async def vibrate(self):
        await self._call("vibrate")

    async def info(self):
        return await self._call("info")
