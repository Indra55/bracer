"""Read private local configuration without evaluating shell expressions."""

import json
import os
from pathlib import Path
import re
import shlex
import tempfile


def read_env(path):
    values = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            raise ValueError(f"Invalid .env syntax on line {number}") from None
        if not tokens:
            continue
        name, separator, value = tokens[0].partition("=")
        if len(tokens) != 1 or not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Expected NAME=value on .env line {number}")
        values[name] = value
    return values


def parse_auth_key(value):
    if not isinstance(value, str):
        raise ValueError("Pairing key must contain exactly 32 hex characters")
    value = value.removeprefix("0x")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise ValueError("Pairing key must contain exactly 32 hex characters")
    return bytes.fromhex(value)


def load_config(path):
    path = Path(path)
    if path.suffix == ".json":
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Config must contain an object")
        address, key = data.get("address"), data.get("auth_key")
    else:
        data = read_env(path)
        address, key = data.get("MIBAND_ADDRESS"), data.get("MIBAND_AUTH_KEY")
    if not isinstance(address, str) or not address.strip():
        raise ValueError("Config needs a nonempty band address")
    return address.strip(), parse_auth_key(key)


def write_env(path, values):
    path = Path(path)
    for name, value in values.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not isinstance(value, str) or any(c in value for c in "\r\n\0"):
            raise ValueError("Invalid .env entry")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            for name, value in values.items():
                output.write(f"{name}={shlex.quote(value)}\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
