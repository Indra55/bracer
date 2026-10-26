import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts.experimental.capture_key import KeyCapture, normalized_address, target_keys


ADDRESS = "A1B2C3D4E5F6"
KEY = "0123456789abcdef0123456789abcdef"


def device(mac="A1:B2:C3:D4:E5:F6", key=KEY):
    return {"macAddress": mac, "additionalInfo": json.dumps({"auth_key": key})}


def flow(data, host="api-mifit.huami.com", path="/users/123/devices"):
    return SimpleNamespace(request=SimpleNamespace(pretty_host=host, path=path),
                           response=SimpleNamespace(get_text=lambda **_: json.dumps(data)))


class CaptureTests(unittest.TestCase):
    def test_only_exact_band_is_selected(self):
        data = {"items": [device(), device("AA:BB:CC:DD:EE:FF", "a" * 32)]}
        self.assertEqual(target_keys(data, ADDRESS), {KEY})
        self.assertIsNone(normalized_address("bad"))
        self.assertEqual(normalized_address("a1-b2-c3-d4-e5-f6"), ADDRESS)

    def test_missing_address_or_invalid_key_is_not_accepted(self):
        for data in [{"auth_key": KEY}, device(key="invalid"), device(key="0" * 31)]:
            self.assertEqual(target_keys(data, ADDRESS), set())

    def test_dictionary_extra_and_prefixed_key(self):
        self.assertEqual(target_keys({"mac": ADDRESS, "additionalInfo": {"authKey": "0x" + KEY}}, ADDRESS), {KEY})

    def test_save_without_secret_logging_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary, "auth-key.txt")
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                addon = KeyCapture(ADDRESS, output)
                addon.response(flow(device()))
                KeyCapture(ADDRESS, output).response(flow(device(key="a" * 32)))
            self.assertEqual(output.read_text().strip(), KEY)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(KEY, captured.getvalue())
            self.assertNotIn("a" * 32, captured.getvalue())

    def test_unrelated_host_and_endpoint_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary, "auth-key.txt")
            addon = KeyCapture(ADDRESS, output)
            addon.response(flow(device(), host="huami.com.example.org"))
            addon.response(flow(device(), path="/account/login"))
            self.assertFalse(output.exists())

    def test_conflicting_keys_are_not_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary, "auth-key.txt")
            with contextlib.redirect_stdout(io.StringIO()):
                KeyCapture(ADDRESS, output).response(flow([device(), device(key="a" * 32)]))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
