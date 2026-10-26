import asyncio
import importlib.util
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from miband_agent.band import BandEvent
from miband_agent.connection import ReconnectingBand
from miband_agent.hook import review_on_service
from miband_agent.service import BandService, ServiceBand, bluetooth_owner, service_status


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


class Transport:
    def __init__(self, *_):
        self.connected = False
        self.generation = 1
        self.events = asyncio.Queue()
        self.show = AsyncMock(return_value=None)
        self.vibrate = AsyncMock(return_value=None)
        self.info = AsyncMock(return_value={"model": "fixture"})

    async def __aenter__(self):
        self.connected = True
        return self

    async def __aexit__(self, *_):
        self.connected = False

    def drop(self):
        self.connected = False
        self.generation += 1
        self.events.put_nowait(BandEvent("disconnect", time.monotonic()))


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    def factory(self, *_):
        band = Transport()
        self.instances.append(band)
        return band

    async def asyncSetUp(self):
        self.instances = []

    async def test_range_drop_reauthenticates_and_does_not_replay_old_display(self):
        async with ReconnectingBand("AA", b"\0" * 16, factory=self.factory, retry_min=0.001) as band:
            await band.wait_connected(1)
            first = self.instances[0]
            generation = band.generation
            await band.show("Old approval")
            first.drop()
            await until(lambda: len(self.instances) == 2 and band.connected)
            self.assertGreater(band.generation, generation)
            self.assertFalse(first.connected)
            self.assertEqual(self.instances[1].show.await_args.args[0], "Ready for requests")
            self.assertNotIn("Old approval", [call.args[0] for call in self.instances[1].show.await_args_list])
            while not band.events.empty():
                band.events.get_nowait()
            first.events.put_nowait(BandEvent("confirm", time.monotonic()))
            self.instances[1].events.put_nowait(BandEvent("next", time.monotonic()))
            self.assertEqual((await asyncio.wait_for(band.events.get(), 1)).action, "next")
            await band.show("Fresh approval")
            self.assertEqual(self.instances[1].show.await_args.args[0], "Fresh approval")
        self.assertFalse(self.instances[-1].connected)

    async def test_absent_band_at_startup_retries(self):
        attempts = 0

        def factory(*_):
            nonlocal attempts
            attempts += 1
            band = Transport()
            if attempts == 1:
                band.__aenter__ = AsyncMock(side_effect=OSError("not nearby"))
            return band

        async with ReconnectingBand("AA", b"\0" * 16, factory=factory, retry_min=0.001) as band:
            await band.wait_connected(1)
            self.assertEqual(attempts, 2)

    async def test_failed_display_is_not_retried_after_reconnect(self):
        async with ReconnectingBand("AA", b"\0" * 16, factory=self.factory, retry_min=0.001) as band:
            await band.wait_connected(1)
            self.instances[0].show.side_effect = OSError("link lost")
            with self.assertRaises(ConnectionError):
                await band.show("Do not replay this")
            await until(lambda: len(self.instances) == 2 and band.connected)
            self.assertEqual(self.instances[1].show.await_count, 1)
            self.assertEqual(self.instances[1].show.await_args.args[0], "Ready for requests")

    async def test_wait_deadline_and_shutdown_while_band_absent(self):
        band = Transport()
        band.__aenter__ = AsyncMock(side_effect=OSError("absent"))
        connection = ReconnectingBand("AA", b"\0" * 16, factory=lambda *_: band, retry_min=0.01)
        async with connection:
            with self.assertRaises(ConnectionError):
                await connection.wait_connected(0.01)
        self.assertTrue(connection._task.done())
        self.assertFalse(connection.connected)


class MemoryReader:
    def __init__(self):
        self.lines = asyncio.Queue()

    async def readline(self):
        return await self.lines.get()


class MemoryWriter:
    def __init__(self, peer, local):
        self.peer, self.local = peer, local
        self.closed = False

    def write(self, data):
        if self.closed:
            raise BrokenPipeError()
        self.peer.lines.put_nowait(data)

    async def drain(self):
        pass

    def close(self):
        if not self.closed:
            self.closed = True
            self.peer.lines.put_nowait(b"")
            self.local.lines.put_nowait(b"")

    async def wait_closed(self):
        pass


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.band = Transport()
        self.band.connected = True
        self.service = BandService(self.band)
        self.tasks = []
        self.forward = asyncio.create_task(self.service.forward())
        self.patch = patch("miband_agent.service.asyncio.open_unix_connection", self.open_connection)
        self.patch.start()
        self.clients = []

    async def open_connection(self, *_args, **_kwargs):
        client_reader, server_reader = MemoryReader(), MemoryReader()
        client_writer = MemoryWriter(server_reader, client_reader)
        server_writer = MemoryWriter(client_reader, server_reader)
        self.tasks.append(asyncio.create_task(self.service.handle(server_reader, server_writer)))
        return client_reader, client_writer

    async def client(self):
        client = ServiceBand(Path("unused.sock"))
        await client.__aenter__()
        self.clients.append(client)
        return client

    async def asyncTearDown(self):
        for client in self.clients:
            await client.__aexit__()
        await self.service.close()
        self.forward.cancel()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(self.forward, *self.tasks, return_exceptions=True)
        self.patch.stop()

    async def test_single_active_session_status_and_lease_release(self):
        first = await self.client()
        await first.show("Fixture")
        self.assertEqual(self.band.show.await_args.args[0], "Fixture")
        with self.assertRaisesRegex(ConnectionError, "busy"):
            await self.client()
        status = await service_status(Path("unused.sock"))
        self.assertTrue(status["busy"])
        await first.__aexit__()
        self.clients.remove(first)
        await until(lambda: self.service.owner is None)
        second = await self.client()
        self.assertTrue(second.connected)

    async def test_drop_reconnect_and_old_generation_request_rejection(self):
        client = await self.client()
        generation = client.generation
        self.band.drop()
        await until(lambda: not client.connected)
        self.band.connected = True
        self.band.generation += 1
        self.band.events.put_nowait(BandEvent("connected", time.monotonic()))
        await client.wait_connected(1)
        self.assertGreater(client.generation, generation)
        await client.show("New request")
        writes = self.band.show.await_count
        self.band.generation += 1
        with self.assertRaisesRegex(ConnectionError, "connection changed"):
            await client.show("Old request")
        self.assertEqual(self.band.show.await_count, writes)

    async def test_service_restart_reattaches_without_reusing_connection_generation(self):
        client = await self.client()
        generation = client.generation
        owner = self.service.owner
        owner.close()
        await until(lambda: not client.connected)
        self.band.generation = 1  # A restarted daemon begins with a fresh counter.
        await until(lambda: client.connected)
        self.assertGreater(client.generation, generation)
        await client.show("Fresh request after service restart")
        self.assertEqual(self.band.show.await_args.args[0], "Fresh request after service restart")

    async def test_connection_failure_is_reported_to_waiting_client(self):
        self.band.connected = False
        client = await self.client()
        self.band.last_error = "Authentication rejected: header=10 83 08"
        self.band.events.put_nowait(BandEvent("connection_error", time.monotonic()))
        await until(lambda: client.last_error == self.band.last_error)
        with self.assertRaisesRegex(ConnectionError, "Authentication rejected"):
            await client.wait_connected(0.01)

    async def test_native_hook_requests_from_multiple_chats_queue_and_scope_decisions(self):
        first = asyncio.create_task(review_on_service({"command": "echo first", "session": "chat-1"}, Path("unused")))
        second = asyncio.create_task(review_on_service({"command": "echo second", "session": "chat-2"}, Path("unused")))
        await until(lambda: len(self.service.approvals.pending) == 2 and self.band.show.await_count > 0)
        self.band.events.put_nowait(BandEvent("confirm", time.monotonic() + 0.01))
        self.assertEqual(await asyncio.wait_for(first, 1), "accept")
        await until(lambda: self.band.show.await_args.args[0].startswith('command: "echo second'))
        self.assertFalse(second.done())
        self.band.events.put_nowait(BandEvent("deny", time.monotonic() + 0.01))
        self.assertEqual(await asyncio.wait_for(second, 1), "decline")

    async def test_native_hook_cancellation_clears_pending_review(self):
        request = asyncio.create_task(review_on_service({"command": "echo cancel"}, Path("unused")))
        await until(lambda: bool(self.service.approvals.pending))
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        await until(lambda: not self.service.approvals.pending)
        self.assertFalse(self.service._review_waiters)

    async def test_native_hook_offline_and_busy_preserve_computer_approval(self):
        self.band.connected = False
        self.assertEqual(await review_on_service({"command": "echo offline"}, Path("unused")), "unavailable")
        self.band.connected = True
        await self.client()
        self.assertEqual(await review_on_service({"command": "echo busy"}, Path("unused")), "unavailable")
        self.band.show.assert_not_awaited()

    async def test_native_hook_pending_requests_decline_after_fast_reconnect(self):
        first = asyncio.create_task(review_on_service({"command": "echo old-1"}, Path("unused")))
        second = asyncio.create_task(review_on_service({"command": "echo old-2"}, Path("unused")))
        await until(lambda: len(self.service.approvals.pending) == 2 and self.band.show.await_count > 0)
        self.band.drop()
        self.band.connected = True
        self.band.generation += 1
        self.assertEqual(await asyncio.wait_for(first, 1), "decline")
        self.assertEqual(await asyncio.wait_for(second, 1), "decline")


class OwnerAndUnitTests(unittest.TestCase):
    def test_bluetooth_owner_excludes_other_processes_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            with bluetooth_owner(path):
                with self.assertRaisesRegex(RuntimeError, "owns Bluetooth"):
                    with bluetooth_owner(path):
                        self.fail("Acquired the same Bluetooth lease twice")
            with bluetooth_owner(path):
                pass

    def test_installer_unit_is_idle_and_never_replays_an_agent_prompt(self):
        spec = importlib.util.spec_from_file_location("installer", Path(__file__).parents[1] / "scripts/install-linux.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        unit = installer.service_unit(Path('/tmp/band test%"$'))
        self.assertIn("WantedBy=default.target", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn(" serve\n", unit)
        self.assertIn("/.env", unit)
        self.assertNotIn(".band.json", unit)
        self.assertNotIn("--resume", unit)
        self.assertNotIn(" run ", unit)
        self.assertIn('test%%\\"$$', unit)
        self.assertIn('WorkingDirectory=/tmp/band test%%"$\n', unit)


class UnixSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_socket_client_and_service(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.sock"
            try:
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.bind(str(path))
                path.unlink()
            except PermissionError:
                self.skipTest("Executor blocks Unix sockets; run on the host")
            band = Transport()
            band.connected = True
            service = BandService(band)
            server = await asyncio.start_unix_server(service.handle, str(path))
            forward = asyncio.create_task(service.forward())
            try:
                async with server, ServiceBand(path) as client:
                    await client.show("Real socket test")
                    self.assertEqual(band.show.await_args.args[0], "Real socket test")
                    band.events.put_nowait(BandEvent("confirm", time.monotonic()))
                    while True:
                        event = await asyncio.wait_for(client.events.get(), 1)
                        if event.action == "confirm":
                            break
            finally:
                forward.cancel()
                await asyncio.gather(forward, return_exceptions=True)
                await service.close()
