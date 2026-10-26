import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from miband_agent.approvals import ApprovalQueue, approval_pages
from miband_agent.band import ALERT, AUTH, CHUNKED, EVENT, Band, BandEvent, music_chunks, music_event, music_payload
from miband_agent.codex import CodexSession
from miband_agent.config import load_config


class FakeBand:
    def __init__(self):
        self.connected = True
        self.events = asyncio.Queue()
        self.frames = asyncio.Queue()
        self.timestamp = time.monotonic()

    async def show(self, text, heading="Codex", hint=""):
        await self.frames.put((text, heading, hint))

    async def vibrate(self):
        pass

    def press(self, action):
        self.timestamp = max(time.monotonic() + 0.01, self.timestamp + 0.5)
        self.events.put_nowait(BandEvent(action, self.timestamp))

    async def frame(self):
        return await asyncio.wait_for(self.frames.get(), 2)


PARAMS = {"threadId": "t1", "turnId": "turn1", "itemId": "item1",
          "command": "python3 --version", "cwd": "/tmp"}


class ProtocolTests(unittest.TestCase):
    def test_music_framing_known_bytes(self):
        self.assertEqual(music_payload("T", "A", "B"), b"\x0f\x01\0\0\0A\0B\0T\0")
        self.assertEqual(list(music_chunks(b"a")), [b"\0\xc3\0a"])
        self.assertEqual([chunk[:3] for chunk in music_chunks(b"a" * 40)],
                         [b"\0\x03\0", b"\0\x43\x01", b"\0\x83\x02"])
        for length in (17, 18, 34, 35, 100):
            data = bytes(range(length))
            chunks = list(music_chunks(data))
            self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
            self.assertEqual(b"".join(chunk[3:] for chunk in chunks), data)

    def test_event_decode_rejects_unrelated_and_malformed_events(self):
        for raw in (b"", b"\xfe", b"\x03\x00", b"\xfe\x03\x00", b"\xfe\xff"):
            self.assertIsNone(music_event(raw))
        self.assertEqual(music_event(b"\xfe\x03"), "next")
        self.assertEqual(music_event(b"\xfe\x04"), "previous")
        self.assertEqual(music_event(b"\xfe\x06"), "deny")
        self.assertEqual(music_event(b"\xfe\x01"), "confirm")

    def test_pages_preserve_full_command_and_scope(self):
        params = dict(PARAMS, command="echo '\u00e9';\nrm\t-- 'x' " * 30,
                      additionalPermissions={"fileSystem": {"write": ["/secret"]}})
        rendered = "".join(approval_pages(params))
        self.assertIn(json.dumps(params["command"], ensure_ascii=True, separators=(",", ":")), rendered)
        self.assertIn("/secret", rendered)
        self.assertIn("cwd", rendered)
        self.assertTrue(all(len(page) <= 32 for page in approval_pages(params)))

    def test_missing_action_is_not_approvable(self):
        with self.assertRaises(ValueError):
            approval_pages({"reason": "just trust me"})
        self.assertIn("host", "".join(approval_pages({"networkApprovalContext": {"host": "example.org", "protocol": "https"}})))

    def test_config_validation_and_no_secret_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary, "config.json")
            config.write_text(json.dumps({"address": "AA:BB", "auth_key": "0x" + "12" * 16}))
            self.assertEqual(load_config(config), ("AA:BB", b"\x12" * 16))
            config.write_text(json.dumps({"address": "AA", "auth_key": "secret!"}))
            with self.assertRaises(ValueError) as error:
                load_config(config)
            self.assertNotIn("secret!", str(error.exception))


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.band = FakeBand()
        self.replies = asyncio.Queue()

        async def reply(request_id, result):
            await self.replies.put((request_id, result))

        self.manager = ApprovalQueue(self.band, reply, timeout=2)
        self.manager.start()

    async def asyncTearDown(self):
        await self.manager.close()

    async def test_accept_from_first_page_scopes_one_request(self):
        self.manager.submit(101, PARAMS)
        await self.band.frame()
        self.band.press("confirm")
        self.assertEqual(await asyncio.wait_for(self.replies.get(), 1), (101, {"decision": "accept"}))

    async def test_navigation_remains_available_before_immediate_approval(self):
        self.manager.submit(101, PARAMS)
        first = await self.band.frame()
        self.band.press("next")
        second = await self.band.frame()
        self.assertNotEqual(first[0], second[0])
        self.band.press("previous")
        self.assertEqual((await self.band.frame())[0], first[0])
        self.band.press("confirm")
        self.assertEqual(await self.replies.get(), (101, {"decision": "accept"}))

    async def test_reconnect_declines_active_and_queued_requests_then_accepts_fresh_request(self):
        self.band.generation = 1
        self.manager.submit(1, PARAMS)
        self.manager.submit(2, PARAMS)
        await self.band.frame()
        self.band.generation = 3
        self.band.press("confirm")
        self.assertEqual(await self.replies.get(), (1, {"decision": "decline"}))
        self.assertEqual(await self.replies.get(), (2, {"decision": "decline"}))
        while not self.band.frames.empty():
            self.band.frames.get_nowait()
        self.manager.submit(3, PARAMS)
        await self.band.frame()
        self.band.press("confirm")
        self.assertEqual(await self.replies.get(), (3, {"decision": "accept"}))

    async def test_offline_request_does_not_become_approvable_after_reconnect(self):
        self.band.connected = False
        self.manager.submit(1, PARAMS)
        self.band.connected = True
        self.assertEqual(await self.replies.get(), (1, {"decision": "decline"}))

    async def test_stale_confirm_is_ignored_on_first_page(self):
        self.manager.submit(1, PARAMS)
        await self.band.frame()
        self.band.events.put_nowait(BandEvent("confirm", 0))
        await asyncio.sleep(0.01)
        self.assertTrue(self.replies.empty())
        self.band.press("confirm")
        self.assertEqual(await self.replies.get(), (1, {"decision": "accept"}))

    async def test_deny_from_first_page(self):
        self.manager.submit("deny", PARAMS)
        await self.band.frame()
        self.band.press("deny")
        self.assertEqual(await self.replies.get(), ("deny", {"decision": "decline"}))

    async def test_disconnect_and_timeout_decline(self):
        self.manager.submit(1, PARAMS)
        await self.band.frame()
        self.band.connected = False
        self.band.press("disconnect")
        self.assertEqual(await self.replies.get(), (1, {"decision": "decline"}))
        self.band.connected = True
        self.manager.timeout = 0.02
        self.manager.submit(2, PARAMS)
        self.assertEqual(await asyncio.wait_for(self.replies.get(), 1), (2, {"decision": "decline"}))

    async def test_external_resolution_cancels_without_second_answer(self):
        self.manager.submit(1, PARAMS)
        await self.band.frame()
        self.manager.resolve(1)
        self.band.press("confirm")
        await asyncio.wait_for(self.manager.queue.join(), 1)
        self.assertTrue(self.replies.empty())

    async def test_fifo_and_old_press_cannot_answer_next_request(self):
        self.manager.submit(1, PARAMS)
        self.manager.submit(2, dict(PARAMS, command="pwd"))
        await self.band.frame()
        self.band.events.put_nowait(BandEvent("confirm", 0))
        self.band.press("deny")
        self.assertEqual(await self.replies.get(), (1, {"decision": "decline"}))
        frame = await self.band.frame()
        while frame[0] == "Waiting for Codex":
            frame = await self.band.frame()
        self.band.events.put_nowait(BandEvent("confirm", 0))
        await asyncio.sleep(0.01)
        self.assertTrue(self.replies.empty())
        self.band.press("deny")
        self.assertEqual(await self.replies.get(), (2, {"decision": "decline"}))

    async def test_display_failure_and_unavailable_accept_decline(self):
        self.band.show = AsyncMock(side_effect=OSError("BLE lost"))
        self.manager.submit(1, PARAMS)
        self.assertEqual(await self.replies.get(), (1, {"decision": "decline"}))
        self.manager.submit(2, dict(PARAMS, availableDecisions=["decline"]))
        self.assertEqual(await self.replies.get(), (2, {"decision": "decline"}))

    async def test_turn_completion_invalidates_queued_requests(self):
        self.manager.submit(1, PARAMS)
        self.manager.submit(2, PARAMS)
        await self.band.frame()
        self.manager.clear_turn("turn1")
        await asyncio.wait_for(self.manager.queue.join(), 1)
        self.assertTrue(self.replies.empty())

    async def test_accept_checks_connection_again(self):
        self.manager.submit(1, PARAMS)
        await self.band.frame()
        self.band.connected = False
        self.band.press("confirm")
        self.assertEqual(await self.replies.get(), (1, {"decision": "decline"}))

    async def test_close_declines_pending(self):
        self.manager.submit(1, PARAMS)
        await self.band.frame()
        # Cancel during a review: worker cleanup must not drop the unanswered ID.
        await self.manager.close()
        self.assertEqual(await asyncio.wait_for(self.replies.get(), 0.2), (1, {"decision": "decline"}))


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_notifications_remain_active_through_music_subscription(self):
        band = Band("AA", b"\0" * 16)
        callbacks = {}
        client = SimpleNamespace(
            is_connected=True,
            services=SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(properties=["write-without-response"])),
            connect=AsyncMock(),
        )

        async def notify(uuid, callback):
            if not client.is_connected:
                raise OSError("Not Connected")
            callbacks[uuid] = callback

        async def disconnect(*_):
            client.is_connected = False

        async def write(uuid, data, response):
            reply = b"\x10\x02\x01" + b"\0" * 16 if data[0] == 0x82 else b"\x10\x03\x01"
            callbacks[AUTH](None, reply)

        client.start_notify = AsyncMock(side_effect=notify)
        client.stop_notify = AsyncMock(side_effect=disconnect)
        client.disconnect = AsyncMock(side_effect=disconnect)
        client.write_gatt_char = AsyncMock(side_effect=write)
        scanner = AsyncMock(return_value=object())
        with patch("bleak.BleakScanner.find_device_by_address", scanner), \
                patch("bleak.BleakClient", return_value=client):
            async with band:
                self.assertTrue(band.connected)
                self.assertEqual(set(callbacks), {AUTH, EVENT})
                client.stop_notify.assert_not_awaited()
                callbacks[EVENT](None, b"\xfe\x03")
                self.assertEqual((await band.events.get()).action, "next")
        client.disconnect.assert_awaited_once()
        self.assertFalse(band.connected)

    async def test_vibration_sends_find_and_stop(self):
        band = Band("AA", b"\0" * 16)

        class Client:
            is_connected = True
            write_gatt_char = AsyncMock()
            services = SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(properties=["write"]))

        band.client = Client()
        await band.vibrate()
        self.assertEqual(band.client.write_gatt_char.call_args_list[0].args, (ALERT, b"\x03"))
        self.assertEqual(band.client.write_gatt_char.call_args_list[1].args, (ALERT, b"\x00"))

    async def test_authentication_uses_encrypted_challenge_not_key_registration(self):
        await self.check_authentication("write", True)

    async def test_authentication_supports_band_with_only_write_without_response(self):
        await self.check_authentication("write-without-response", False)

    async def check_authentication(self, property_name, response, challenge_reply=None,
                                   result_reply=b"\x10\x03\x01"):
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plain = bytes.fromhex("00112233445566778899aabbccddeeff")
        ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        band = Band("AA", key)

        class Client:
            is_connected = True
            services = SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(properties=[property_name]))

            def __init__(self):
                self.writes = []

            async def start_notify(self, uuid, callback):
                self.callback = callback

            async def stop_notify(self, uuid):
                pass

            async def write_gatt_char(client, uuid, data, response):
                # Mi Band 5 inherits authFlags=0x00 and cryptFlags=0x80 in Gadgetbridge.
                expected = b"\x82\x00\x02\x01\x00" if not client.writes else b"\x83\x00" + ciphertext
                self.assertEqual(data, expected)
                client.writes.append((uuid, data, response))
                challenge = b"\x10\x02\x01" + plain if challenge_reply is None else challenge_reply
                client.callback(None, challenge if len(client.writes) == 1 else result_reply)

        band.client = Client()
        await band._authenticate()
        self.assertEqual(band.client.writes, [(AUTH, b"\x82\x00\x02\x01\x00", response),
                                              (AUTH, b"\x83\x00" + ciphertext, response)])

    async def test_auth_rejections_report_only_status_header_and_length(self):
        for phase, reply in (("challenge", b"\x10\x02\x04"),
                             ("result", b"\x10\x03\x04"),
                             ("result", b"\x10\x02\x01"),
                             ("challenge", b""), ("result", b"")):
            with self.subTest(phase=phase, header=reply):
                packet = reply + b"private payload" if reply else reply
                kwargs = {"challenge_reply" if phase == "challenge" else "result_reply": packet}
                with self.assertRaises(RuntimeError) as caught:
                    await self.check_authentication("write-without-response", False, **kwargs)
                message = str(caught.exception)
                self.assertIn(f"header={reply.hex(' ')}", message)
                self.assertIn(f"length={len(packet)}", message)
                self.assertNotIn(b"private payload".hex(), message)
                self.assertNotIn("private payload", message)

    async def test_music_supports_write_only_characteristic(self):
        band = Band("AA", b"\0" * 16)
        band.client = SimpleNamespace(
            services=SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(properties=["write"])),
            write_gatt_char=AsyncMock(),
        )
        await band.show("Test")
        for call in band.client.write_gatt_char.call_args_list:
            self.assertEqual(call.args[0], CHUNKED)
            self.assertTrue(call.kwargs["response"])

    async def test_auth_write_error_identifies_operation_without_secret(self):
        from bleak.exc import BleakGATTProtocolError
        band = Band("AA", b"\x12" * 16)
        write = AsyncMock(side_effect=BleakGATTProtocolError(6))
        band.client = SimpleNamespace(
            is_connected=True,
            services=SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(properties=["write"])),
            start_notify=AsyncMock(),
            stop_notify=AsyncMock(side_effect=OSError("cleanup failed")),
            write_gatt_char=write,
        )
        with self.assertRaises(RuntimeError) as caught:
            await band._authenticate()
        message = str(caught.exception)
        self.assertIn(AUTH, message)
        self.assertIn("Write with response", message)
        self.assertIn("Request Not Supported", message)
        self.assertNotIn(band.key.hex(), message)
        self.assertNotIn("cleanup failed", message)
        self.assertEqual(write.await_count, 1)
        band.client.stop_notify.assert_not_awaited()

    async def test_nonwritable_characteristic_sends_nothing(self):
        band = Band("AA", b"\0" * 16)
        band.client = SimpleNamespace(
            services=SimpleNamespace(get_characteristic=lambda _: SimpleNamespace(properties=["notify"])),
            write_gatt_char=AsyncMock(),
        )
        with self.assertRaisesRegex(RuntimeError, "not writable"):
            await band._write(AUTH, b"test")
        band.client.write_gatt_char.assert_not_awaited()


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_subprocess_protocol_with_fake_codex_and_band(self):
        import sys
        band = FakeBand()
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary, "codex-fixture")
            script.write_text(f"#!{sys.executable}\n" + '''
import json,sys
def send(value):
 print(json.dumps(value), flush=True)
def receive():
 return json.loads(sys.stdin.readline())
message=receive()
assert message['method']=='initialize'
send({'id':message['id'],'result':{}})
assert receive()['method']=='initialized'
message=receive()
assert message['method']=='thread/start'
assert message['params']['approvalPolicy']=='on-request'
assert message['params']['sandbox']=='workspace-write'
send({'id':message['id'],'result':{'thread':{'id':'fixture-thread'}}})
message=receive()
assert message['method']=='turn/start'
send({'id':message['id'],'result':{'turn':{'id':'turn1'}}})
for request_id,expected in [(100,'accept'),(101,'decline')]:
 send({'id':request_id,'method':'item/commandExecution/requestApproval','params':{
  'threadId':'fixture-thread','turnId':'turn1','itemId':str(request_id),'command':'echo fixture','cwd':'/tmp'}})
 assert receive()=={'id':request_id,'result':{'decision':expected}}
 send({'method':'serverRequest/resolved','params':{'requestId':request_id,'threadId':'fixture-thread'}})
send({'id':102,'method':'item/fileChange/requestApproval','params':{}})
assert receive()=={'id':102,'result':{'decision':'decline'}}
send({'method':'turn/completed','params':{'turn':{'id':'turn1','status':'completed'}}})
sys.stdin.read()
''')
            script.chmod(0o700)
            session = CodexSession(band, timeout=5)
            task = asyncio.create_task(session.run("fixture", Path(temporary), str(script)))
            frame = await band.frame()
            while "Play YES" not in frame[2]:
                band.press("next")
                frame = await band.frame()
            band.press("confirm")
            frame = await band.frame()
            while frame[0] == "Waiting for Codex":
                frame = await band.frame()
            band.press("deny")
            self.assertEqual(await asyncio.wait_for(task, 5), "completed")


if __name__ == "__main__":
    unittest.main()
