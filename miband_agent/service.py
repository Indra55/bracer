"""One Bluetooth owner, reached through an owner-only local Unix socket."""

import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import time

from .band import BandEvent
from .config import load_config
from .connection import ReconnectingBand
from .approvals import ApprovalQueue


def default_socket():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    root = Path(runtime) / "miband-agent" if runtime else Path(f"/tmp/miband-agent-{os.getuid()}")
    return root / "bridge.sock"


@contextmanager
def bluetooth_owner(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = path.parent.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid() or directory.st_mode & 0o077:
        raise RuntimeError("Band socket directory must be owned by you with mode 0700")
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another bridge owns Bluetooth; use its service socket") from None
        yield
    finally:
        os.close(fd)


async def send(writer, message):
    writer.write(json.dumps(message).encode() + b"\n")
    await asyncio.wait_for(writer.drain(), 5)


class ReviewBand:
    def __init__(self, band):
        self.band = band
        self.events = asyncio.Queue()

    def __getattr__(self, name):
        return getattr(self.band, name)


class BandService:
    def __init__(self, band):
        self.band = band
        self.owner = None
        self._clients = set()
        self._review_band = ReviewBand(band)
        self._review_waiters = {}
        self._reviews = set()
        self.approvals = ApprovalQueue(self._review_band, self._reply_review, timeout=120)

    def state(self):
        return {"connected": self.band.connected, "generation": self.band.generation,
                "busy": self.owner is not None or bool(self.approvals.pending),
                "pending_reviews": len(self.approvals.pending), "error": getattr(self.band, "last_error", None)}

    async def _reply_review(self, request_id, result):
        future = self._review_waiters.get(request_id)
        if future is not None and not future.done():
            future.set_result(result)

    async def review(self, request_id, params, writer):
        token = secrets.token_hex(16)
        try:
            if not isinstance(params, dict) or not isinstance(params.get("command"), str) or not params["command"]:
                raise ValueError("A command is required for band review")
            if self.owner is not None or not self.band.connected:
                await send(writer, {"id": request_id, "result": {"decision": "unavailable"}})
                return
            future = asyncio.get_running_loop().create_future()
            self._review_waiters[token] = future
            if self.approvals.task is None:
                self.approvals.start()
            self.approvals.submit(token, params)
            await send(writer, {"id": request_id, "result": await future})
        except Exception:
            try:
                await send(writer, {"id": request_id, "result": {"decision": "unavailable"}})
            except (OSError, TimeoutError):
                pass
        finally:
            self.approvals.resolve(token)
            self._review_waiters.pop(token, None)

    async def forward(self):
        while True:
            event = await self.band.events.get()
            if self.approvals.pending:
                self._review_band.events.put_nowait(event)
            writer = self.owner
            if writer is None:
                continue
            message = {"state": self.state()} if event.action in {"connected", "disconnect", "connection_error"} else {
                "event": event.action, "at": event.at, "generation": self.band.generation,
            }
            try:
                await send(writer, message)
            except (OSError, TimeoutError):
                writer.close()

    async def handle(self, reader, writer):
        self._clients.add(writer)
        reviews = set()
        try:
            while line := await reader.readline():
                request = json.loads(line)
                method = request.get("method")
                request_id = request.get("id")
                try:
                    if method == "review":
                        task = asyncio.create_task(self.review(request_id, request.get("params"), writer))
                        reviews.add(task)
                        self._reviews.add(task)
                        task.add_done_callback(reviews.discard)
                        task.add_done_callback(self._reviews.discard)
                        continue
                    elif method == "status":
                        result = self.state()
                    elif method == "attach":
                        if self.approvals.pending or (self.owner is not None and self.owner is not writer):
                            raise RuntimeError("Band is busy with another session")
                        self.owner = writer
                        result = self.state()
                    elif method in {"show", "vibrate", "info"}:
                        if self.owner is not writer:
                            raise RuntimeError("Attach before using the band")
                        if request.get("generation") != self.band.generation or not self.band.connected:
                            raise ConnectionError("Band connection changed; request discarded")
                        args = request.get("args", [])
                        if not isinstance(args, list):
                            raise ValueError("Invalid arguments")
                        if method == "show" and (len(args) != 3 or not all(isinstance(arg, str) for arg in args)):
                            raise ValueError("Show needs three text fields")
                        if method != "show" and args:
                            raise ValueError("Unexpected arguments")
                        result = await getattr(self.band, method)(*args)
                    else:
                        raise ValueError("Unknown band operation")
                    await send(writer, {"id": request_id, "result": result})
                except Exception as error:
                    await send(writer, {"id": request_id, "error": str(error)})
        except (OSError, ValueError, TypeError, AttributeError, TimeoutError):
            pass
        finally:
            for task in list(reviews):
                task.cancel()
            await asyncio.gather(*reviews, return_exceptions=True)
            if self.owner is writer:
                self.owner = None
            self._clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def close(self):
        for task in list(self._reviews):
            task.cancel()
        await asyncio.gather(*self._reviews, return_exceptions=True)
        await self.approvals.close()
        for writer in list(self._clients):
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for writer in list(self._clients)), return_exceptions=True)


async def serve(config, path):
    with bluetooth_owner(path):
        if path.exists():
            if not stat.S_ISSOCK(path.lstat().st_mode):
                raise RuntimeError("Refusing to replace a non-socket file")
            path.unlink()
        async with ReconnectingBand(*load_config(config)) as band:
            service = BandService(band)
            server = await asyncio.start_unix_server(service.handle, path=str(path), limit=16384)
            path.chmod(0o600)
            forward = asyncio.create_task(service.forward())
            print(f"Band service listening at {path}", flush=True)
            try:
                async with server:
                    await server.serve_forever()
            finally:
                forward.cancel()
                await asyncio.gather(forward, return_exceptions=True)
                await service.close()
                path.unlink(missing_ok=True)


class ServiceBand:
    def __init__(self, path):
        self.path = path
        self.events = asyncio.Queue()
        self.generation = 0
        self.connected = False
        self.last_error = None
        self._ready = asyncio.Event()
        self._pending = {}
        self._sequence = 0
        self._writer = None
        self._reader_task = None
        self._reconnect_task = None
        self._closing = False
        self._server_generation = 0

    async def __aenter__(self):
        try:
            reader, self._writer = await asyncio.open_unix_connection(str(self.path), limit=16384)
        except OSError as error:
            raise ConnectionError("Band service is unavailable; run systemctl --user restart miband-agent.service") from error
        self._reader_task = asyncio.create_task(self._read(reader))
        try:
            self._state(await self._request("attach"))
            if self._reader_task.done():
                raise ConnectionError("Band service disconnected during attach")
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def __aexit__(self, *_):
        self._closing = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            await asyncio.gather(self._reconnect_task, return_exceptions=True)
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        if self._reader_task:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
        self.connected = False
        self._ready.clear()

    def _state(self, state):
        was_connected = self.connected
        old_error = self.last_error
        self.last_error = state.get("error", self.last_error)
        if self.last_error and self.last_error != old_error:
            print(f"Band unavailable: {self.last_error}", flush=True)
        old_generation = self._server_generation
        self.connected, self._server_generation = state["connected"], state["generation"]
        changed = was_connected != self.connected or old_generation != self._server_generation
        if changed:
            self.generation += 1
        if self.connected:
            self._ready.set()
        else:
            self._ready.clear()
        if was_connected and changed:
            self.events.put_nowait(BandEvent("disconnect", time.monotonic()))
        if self.connected and changed:
            self.events.put_nowait(BandEvent("connected", time.monotonic()))

    async def _read(self, reader):
        try:
            while line := await reader.readline():
                message = json.loads(line)
                if "state" in message:
                    self._state(message["state"])
                elif "event" in message:
                    if self.connected and message["generation"] == self._server_generation:
                        self.events.put_nowait(BandEvent(message["event"], message["at"]))
                elif message.get("id") in self._pending:
                    future = self._pending[message["id"]]
                    if not future.done():
                        if "error" in message:
                            future.set_exception(ConnectionError(message["error"]))
                        else:
                            future.set_result(message.get("result"))
        finally:
            self._state({"connected": False, "generation": self._server_generation})
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Band service disconnected"))
            if not self._closing and self._reconnect_task is None:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self):
        delay = 1
        try:
            while True:
                await asyncio.sleep(delay)
                try:
                    reader, self._writer = await asyncio.open_unix_connection(str(self.path), limit=16384)
                    self._reader_task = asyncio.create_task(self._read(reader))
                    state = await self._request("attach")
                    if self._reader_task.done():
                        raise ConnectionError("Band service disconnected during attach")
                    self._state(state)
                    print("Band service connection restored.", flush=True)
                    return
                except (OSError, ConnectionError, TimeoutError):
                    self._writer.close()
                    if self._reader_task:
                        self._reader_task.cancel()
                        await asyncio.gather(self._reader_task, return_exceptions=True)
                delay = min(30, delay * 2)
        finally:
            self._reconnect_task = None

    async def _request(self, method, *args):
        if self._reader_task.done():
            raise ConnectionError("Band service is reconnecting")
        self._sequence += 1
        request_id = self._sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            try:
                await send(self._writer, {"id": request_id, "method": method, "args": list(args),
                                          "generation": self._server_generation})
            except (OSError, TimeoutError) as error:
                self._writer.close()
                raise ConnectionError("Band service connection lost; reconnecting") from error
            try:
                return await asyncio.wait_for(future, 20)
            except TimeoutError as error:
                self._writer.close()
                raise ConnectionError("Band service did not respond; reconnecting") from error
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def wait_connected(self, timeout=90):
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except TimeoutError:
            detail = self.last_error or "No successful connection yet"
            raise ConnectionError(f"Band connection wait timed out: {detail}. Service keeps retrying") from None

    async def show(self, text, heading="Codex", hint="Next/Prev | Vol- NO"):
        await self._request("show", text, heading, hint)

    async def vibrate(self):
        await self._request("vibrate")

    async def info(self):
        return await self._request("info")


async def service_status(path):
    reader, writer = await asyncio.open_unix_connection(str(path))
    try:
        await send(writer, {"id": 1, "method": "status"})
        response = json.loads(await asyncio.wait_for(reader.readline(), 5))
        return response["result"]
    finally:
        writer.close()
        await writer.wait_closed()
