import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field


COMMAND_APPROVAL = "item/commandExecution/requestApproval"


def approval_pages(params, width=32):
    # Include every field, including future permission fields. ASCII escapes keep
    # control characters and unsupported glyphs visible instead of hiding them.
    pages = []
    for key, value in params.items():
        if key in {"threadId", "turnId", "itemId", "startedAtMs"} or value is None:
            continue
        line = key + ": " + json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        pages.extend(line[i:i + width] for i in range(0, len(line), width))
    if not params.get("command") and not params.get("networkApprovalContext"):
        raise ValueError("Approval has no command or network destination to review")
    return pages


@dataclass
class Pending:
    request_id: object
    params: dict
    deadline: float
    generation: int = 0
    available: bool = True
    tag: str = field(default_factory=lambda: secrets.token_hex(2))
    valid: bool = True
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)


class ApprovalQueue:
    def __init__(self, band, reply, timeout=180):
        self.band, self.reply, self.timeout = band, reply, timeout
        self.queue = asyncio.Queue()
        self.pending = {}
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self._worker())

    def submit(self, request_id, params):
        if request_id in self.pending:
            raise RuntimeError("Duplicate approval request ID")
        pending = Pending(request_id, params, time.monotonic() + self.timeout)
        pending.generation = getattr(self.band, "generation", 0)
        pending.available = self.band.connected
        self.pending[request_id] = pending
        self.queue.put_nowait(pending)

    def resolve(self, request_id):
        pending = self.pending.get(request_id)
        if pending:
            pending.valid = False
            pending.cancelled.set()

    def clear_turn(self, turn_id):
        for pending in list(self.pending.values()):
            if pending.params.get("turnId") == turn_id:
                self.resolve(pending.request_id)

    async def close(self):
        unanswered = list(self.pending.values())
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for pending in unanswered:
            if pending.valid:
                pending.valid = False
                await self.reply(pending.request_id, {"decision": "decline"})
        self.pending.clear()

    async def _worker(self):
        while True:
            pending = await self.queue.get()
            try:
                if not pending.valid:
                    continue
                try:
                    decision = await self._review(pending)
                except Exception as error:
                    print(f"Band review failed ({type(error).__name__}); declining request", flush=True)
                    decision = "decline"
                if pending.valid:
                    if decision == "accept" and (not self._same_connection(pending) or time.monotonic() >= pending.deadline):
                        decision = "decline"
                    pending.valid = False
                    await self.reply(pending.request_id, {"decision": decision})
                    print(f"Approval {pending.tag}: {decision}", flush=True)
                if self.band.connected:
                    try:
                        await self.band.show("Waiting for Codex", "Codex", "No approval active")
                    except Exception:
                        pass
            finally:
                self.pending.pop(pending.request_id, None)
                self.queue.task_done()

    async def _next_event(self, pending):
        event = asyncio.create_task(self.band.events.get())
        cancelled = asyncio.create_task(pending.cancelled.wait())
        try:
            done, _ = await asyncio.wait(
                {event, cancelled}, timeout=max(0, pending.deadline - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done or not done:
                return None
            return event.result()
        finally:
            for task in (event, cancelled):
                task.cancel()
            await asyncio.gather(event, cancelled, return_exceptions=True)

    async def _review(self, pending):
        if not self._same_connection(pending) or time.monotonic() >= pending.deadline:
            return "decline"
        pages = approval_pages(pending.params)
        decisions = pending.params.get("availableDecisions")
        if decisions is not None and "accept" not in decisions:
            return "decline"
        index = 0

        async def render():
            if not self._same_connection(pending):
                raise ConnectionError("Band connection changed during approval")
            remaining = max(0, int(pending.deadline - time.monotonic()))
            hint = "Play YES | Vol- NO"
            await self.band.show(pages[index], f"{pending.tag} {index+1}/{len(pages)} {remaining}s", hint)
            # Events received while the new page was being written are stale.
            return time.monotonic()

        ready_at = await render()
        await self.band.vibrate()
        last_action = 0
        while pending.valid:
            event = await self._next_event(pending)
            if event is None or not self._same_connection(pending):
                return "decline"
            if event.at <= ready_at:
                continue
            if event.action == "disconnect":
                return "decline"
            if event.action == "open":
                await asyncio.sleep(0.1)
                ready_at = await render()
                continue
            if event.action == "close":
                index = 0
                ready_at = await render()
                continue
            if event.action == "deny":
                return "decline"
            if event.action == "confirm":
                return "accept"
            if event.at - last_action < 0.4:
                continue
            last_action = event.at
            if event.action == "next" and index < len(pages) - 1:
                index += 1
                ready_at = await render()
            elif event.action == "previous" and index > 0:
                index -= 1
                ready_at = await render()
        return "decline"

    def _same_connection(self, pending):
        return pending.available and self.band.connected and pending.generation == getattr(self.band, "generation", 0)
