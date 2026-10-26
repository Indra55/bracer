import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from miband_agent.__main__ import parser, save_config
from miband_agent.config import load_config, parse_auth_key, read_env, write_env
from scripts.experimental.fetch_account_key import load_credentials


KEY = "0123456789abcdef0123456789abcdef"


class ConfigurationTests(unittest.TestCase):
    def test_env_round_trip_preserves_special_characters_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            values = {"MIBAND_ADDRESS": "AA:BB:CC:DD:EE:FF", "MIBAND_AUTH_KEY": KEY,
                      "ZEPP_PASSWORD": "space # ' double\" \\ $HOME $(touch forbidden) `id` = end"}
            write_env(path, values)
            self.assertEqual(read_env(path), values)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_config(path), (values["MIBAND_ADDRESS"], bytes.fromhex(KEY)))
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_setup_preserves_account_credentials_and_replaces_band_key_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            path, key_file = Path(directory) / ".env", Path(directory) / "key.txt"
            write_env(path, {"ZEPP_EMAIL": "test@example.invalid", "ZEPP_PASSWORD": "keep # this",
                             "MIBAND_AUTH_KEY": "a" * 32})
            path.chmod(0o644)
            key_file.write_text("0x" + KEY)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                save_config(SimpleNamespace(config=path, key_file=key_file, address=" AA:BB "))
            self.assertEqual(read_env(path)["ZEPP_PASSWORD"], "keep # this")
            self.assertEqual(read_env(path)["ZEPP_EMAIL"], "test@example.invalid")
            self.assertEqual(load_config(path), ("AA:BB", bytes.fromhex(KEY)))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(KEY, output.getvalue())
            self.assertNotIn("keep # this", output.getvalue())

    def test_failed_atomic_replace_keeps_existing_configuration_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            write_env(path, {"ZEPP_PASSWORD": "original"})
            with patch("miband_agent.config.os.replace", side_effect=OSError("fixture")):
                with self.assertRaises(OSError):
                    write_env(path, {"ZEPP_PASSWORD": "replacement"})
            self.assertEqual(read_env(path), {"ZEPP_PASSWORD": "original"})
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_invalid_config_shapes_raise_value_errors_without_disclosing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            for data in ([], None, {"address": "AA", "auth_key": ["private"]},
                         {"address": "AA", "auth_key": "private"}, {"address": "", "auth_key": KEY}):
                with self.subTest(data=data):
                    path.write_text(json.dumps(data))
                    with self.assertRaises(ValueError) as error:
                        load_config(path)
                    self.assertNotIn("private", str(error.exception))

    def test_malformed_env_diagnostics_do_not_quote_secret_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            for value in ("ZEPP_PASSWORD='private", "ZEPP_PASSWORD=private unquoted", "BAD-NAME=private"):
                path.write_text(value)
                with self.assertRaises(ValueError) as error:
                    read_env(path)
                self.assertNotIn("private", str(error.exception))

    def test_comment_lines_empty_values_and_quoted_hash_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# comment\nZEPP_EMAIL=\nZEPP_PASSWORD='a#b' # comment\n")
            self.assertEqual(read_env(path), {"ZEPP_EMAIL": "", "ZEPP_PASSWORD": "a#b"})

    def test_legacy_json_is_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps({"address": " AA:BB ", "auth_key": "0x" + KEY}))
            self.assertEqual(load_config(path), ("AA:BB", bytes.fromhex(KEY)))

    def test_auth_key_rejects_wrong_types_lengths_and_non_hex(self):
        for key in (None, [], 42, "a" * 31, "z" * 32, "a" * 33):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_auth_key(key)

    def test_cli_defaults_to_env(self):
        self.assertEqual(parser().parse_args(["status"]).config, Path(".env"))

    def test_experimental_helper_reads_only_owner_private_env_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            write_env(path, {"ZEPP_EMAIL": "test@example.invalid", "ZEPP_PASSWORD": "a # password"})
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(load_credentials(path), ("test@example.invalid", "a # password"))
            path.chmod(0o644)
            with self.assertRaises(SystemExit):
                load_credentials(path)


if __name__ == "__main__":
    unittest.main()
