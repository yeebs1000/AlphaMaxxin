"""In-process run registry + progress event bus for SSE."""
import asyncio
import datetime
import uuid


class Run:
    def __init__(self, config: dict):
        self.id = uuid.uuid4().hex[:12]
        self.config = config
        self.status = "running"      # running | done | error
        self.report_id: str | None = None
        self.error: str | None = None
        self.events: list[dict] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def emit(self, stage: str, message: str, pct: int, role: str | None = None):
        event = {"stage": stage, "message": message, "pct": pct, "role": role,
                 "status": self.status}
        self.events.append(event)
        self._queue.put_nowait(event)

    def finish(self, report_id: str):
        self.status = "done"
        self.report_id = report_id
        self.emit("done", "Report ready", 100)
        self._queue.put_nowait(None)  # sentinel closes the SSE stream

    def fail(self, error: str):
        self.status = "error"
        self.error = error
        self.emit("error", error, 100)
        self._queue.put_nowait(None)

    async def stream(self):
        """Replay past events, then live ones until the run completes."""
        for event in list(self.events):
            yield event
        if self.status != "running":
            return
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    def snapshot(self) -> dict:
        return {"run_id": self.id, "status": self.status,
                "report_id": self.report_id, "error": self.error,
                "events": self.events[-10:], "started_at": self.started_at}


class RunRegistry:
    def __init__(self, max_kept: int = 50):
        self._runs: dict[str, Run] = {}
        self._max_kept = max_kept

    def create(self, config: dict) -> Run:
        run = Run(config)
        self._runs[run.id] = run
        while len(self._runs) > self._max_kept:
            oldest = next(iter(self._runs))
            del self._runs[oldest]
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)


RUNS = RunRegistry()
