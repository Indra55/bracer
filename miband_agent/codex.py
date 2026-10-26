import asyncio
import json
import sys
import time

from . import __version__
from .approvals import ApprovalQueue, COMMAND_APPROVAL


class AppServer:
    def __init__(self, command, on_message):
        self.command, self.on_message = command, on_message
        self.process = None
        self.waiters = {}
        self.sequence = 0
        self.reader = None
        self._write_lock = asyncio.Lock()

    async def __aenter__(self):
        self.process = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=None, limit=8 * 1024 * 1024,
        )
        self.reader = asyncio.create_task(self._read())
        try:
            await self.request("initialize", {
                "clientInfo": {"name": "miband_agent", "version": __version__},
                "capabilities": {"experimentalApi": False},
            })
            await self.send({"method": "initialized"})
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def __aexit__(self, *_):
        if self.process and self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)

    async def send(self, message):
        async with self._write_lock:
            self.process.stdin.write(json.dumps(message).encode() + b"\n")
            await self.process.stdin.drain()

    async def reply(self, request_id, result):
        await self.send({"id": request_id, "result": result})

    async def request(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.waiters[request_id] = future
        try:
            await self.send({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, 30)
        finally:
            self.waiters.pop(request_id, None)

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message:
                    await self.on_message(message)
                elif message.get("id") in self.waiters:
                    future = self.waiters[message["id"]]
                    if future.done():
                        continue
                    if "error" in message:
                        future.set_exception(RuntimeError(str(message["error"])))
                    else:
                        future.set_result(message.get("result"))
            raise RuntimeError("Codex app-server disconnected")
        except BaseException as error:
            for future in self.waiters.values():
                if not future.done():
                    future.set_exception(RuntimeError("Codex app-server connection closed"))
            raise error


class CodexSession:
    def __init__(self, band, timeout=180):
        self.band, self.timeout = band, timeout
        self.approvals = None
        self.server = None
        self.finished = asyncio.Event()
        self.thread_id = None
        self.status = None
        self._last_status = 0

    async def show_status(self, text):
        if not self.band.connected or self.approvals.pending or time.monotonic() - self._last_status < 3:
            return
        self._last_status = time.monotonic()
        preview = json.dumps(text, ensure_ascii=True)[1:-1][:32]
        try:
            await self.band.show(preview, "Codex working", "No approval active")
        except ConnectionError:
            print("\nBand disconnected; reconnecting. New approvals decline while offline.", flush=True)

    async def on_message(self, message):
        method = message["method"]
        params = message.get("params", {})
        if "id" in message:
            request_id = message["id"]
            if method == COMMAND_APPROVAL:
                self.approvals.submit(request_id, params)
            elif method == "item/fileChange/requestApproval":
                print("File-change approval declined: patch review is not supported on this band yet", flush=True)
                await self.server.reply(request_id, {"decision": "decline"})
            elif method == "item/permissions/requestApproval":
                await self.server.reply(request_id, {"permissions": {}, "scope": "turn"})
            elif method == "mcpServer/elicitation/request":
                await self.server.reply(request_id, {"action": "decline", "content": None})
            elif method in {"item/tool/requestUserInput", "tool/requestUserInput"}:
                print("Codex asked a question; no answer submitted. Resume at your computer to respond.", flush=True)
                await self.server.reply(request_id, {"answers": {}})
            else:
                print(f"Unsupported Codex request: {method}", flush=True)
                await self.server.send({"id": request_id, "error": {"code": -32601, "message": "Unsupported request"}})
        elif method == "serverRequest/resolved":
            self.approvals.resolve(params.get("requestId"))
        elif method == "item/agentMessage/delta":
            print(params.get("delta", ""), end="", flush=True)
            await self.show_status(params.get("delta", "Working"))
        elif method == "item/started":
            item = params.get("item", {})
            if item.get("type") == "commandExecution":
                await self.show_status(item.get("command", "Running command"))
        elif method == "item/completed":
            item = params.get("item", {})
            if item.get("type") == "commandExecution":
                print(f"\n[Codex command: {item.get('status', 'finished')}]", flush=True)
        elif method == "turn/completed":
            turn = params.get("turn", {})
            self.approvals.clear_turn(turn.get("id"))
            self.status = turn.get("status", "completed")
            self.finished.set()
        elif method == "error":
            print(f"\nCodex: {params.get('error', {}).get('message', 'error')}", file=sys.stderr)

    async def run(self, prompt, cwd, executable="codex", sandbox="workspace-write", resume=None):
        self.server = AppServer([executable, "app-server", "--listen", "stdio://"], self.on_message)
        self.approvals = ApprovalQueue(self.band, self.server.reply, self.timeout)
        async with self.server:
            self.approvals.start()
            try:
                method = "thread/resume" if resume else "thread/start"
                params = {"cwd": str(cwd), "approvalPolicy": "on-request", "sandbox": sandbox,
                          "config": {"approvals_reviewer": "user"}}
                if resume:
                    params["threadId"] = resume
                result = await self.server.request(method, params)
                self.thread_id = result["thread"]["id"]
                print(f"Codex thread: {self.thread_id}", flush=True)
                await self.server.request("turn/start", {
                    "threadId": self.thread_id,
                    "input": [{"type": "text", "text": prompt}],
                })
                done = asyncio.create_task(self.finished.wait())
                try:
                    finished, _ = await asyncio.wait(
                        {done, self.server.reader, self.approvals.task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in finished:
                        if task is not done:
                            task.result()
                finally:
                    done.cancel()
                    await asyncio.gather(done, return_exceptions=True)
            finally:
                await self.approvals.close()
            if self.band.connected:
                try:
                    await self.band.show(f"Task {self.status}", "Codex", "Check terminal for details")
                    await self.band.vibrate()
                except ConnectionError:
                    print("Band completion update unavailable; see terminal result.", flush=True)
            print(f"\nCodex turn: {self.status}", flush=True)
            return self.status
