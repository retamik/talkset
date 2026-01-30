import asyncio
from config import settings
from backend.crud_sqlite import finalize_due_batches


class BatchScheduler:
    def __init__(self, tick_seconds: int = 60):
        self._tick_seconds = tick_seconds
        self._task = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                results = finalize_due_batches(settings.batch_window_seconds)
                for r in results:
                    print(" batch finalized:", r)
            except Exception as e:
                print("Scheduler error:", e)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
            except asyncio.TimeoutError:
                pass
