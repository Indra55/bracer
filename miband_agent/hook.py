"""Route native Codex command permission requests to the band service."""

import asyncio
import contextlib
import json
import sys

from .service import default_socket, send


def review_params(event):
    if not isinstance(event, dict) or event.get("hook_event_name") != "PermissionRequest":
        return None
    if event.get("tool_name") not in {"Bash", "exec_command", "shell", "shell_command"}:
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("command"), str) or not tool_input["command"]:
        return None
    params = {"command": tool_input["command"], "cwd": event.get("cwd", ""),
              "reason": tool_input.get("description"), "session": event.get("session_id", "")}
    if event.get("turn_id"):
        params["turnId"] = event["turn_id"]
    # Preserve other supplied approval context for optional page-by-page review.
    extra = {key: value for key, value in tool_input.items() if key not in {"command", "description"}}
    if extra:
        params["details"] = extra
    return params


def hook_result(decision):
    if decision not in {"accept", "decline"}:
        return {}
    result = {"behavior": "allow" if decision == "accept" else "deny"}
    if decision == "decline":
        result["message"] = "Mi Band review was declined, expired, or disconnected."
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": result}}


async def review_on_service(params, path=None):
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(path or default_socket()), limit=16384), 3)
    try:
        await send(writer, {"id": 1, "method": "review", "params": params})
        response = json.loads(await asyncio.wait_for(reader.readline(), 150))
        if response.get("id") != 1:
            raise ValueError("Unexpected band service response")
        return response.get("result", {}).get("decision", "unavailable")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


def entrypoint():
    result = {}
    try:
        event = json.load(sys.stdin)
        params = review_params(event)
        if params is not None:
            with contextlib.redirect_stdout(sys.stderr):
                decision = asyncio.run(review_on_service(params))
            result = hook_result(decision)
            if not result:
                print("Mi Band unavailable; using the normal Codex approval prompt.", file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, TimeoutError):
        print("Mi Band unavailable; using the normal Codex approval prompt.", file=sys.stderr)
    print(json.dumps(result), flush=True)
    return 0
