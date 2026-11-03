"""Privi Fast Lane: classical parallel model racing, not quantum hardware.

Bounded per-user/project response cache and first-success cancellation. All keys
are supplied by the caller; no personal prompt is stored as the cache key.
"""
import asyncio
import time
from collections import OrderedDict


class FastCache:
    def __init__(self, capacity=128, ttl_seconds=180, clock=None):
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.monotonic
        self.entries = OrderedDict()

    def get(self, key):
        item = self.entries.get(key)
        if item is None:
            return None
        expires, response = item
        if expires <= self.clock():
            self.entries.pop(key, None)
            return None
        self.entries.move_to_end(key)
        return response

    def put(self, key, value):
        self.entries[key] = (self.clock() + self.ttl_seconds, value)
        self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)


cache = FastCache()


async def first_success(workers, timeout_seconds=75):
    """Race named coroutine factories, cancel unfinished work once one succeeds.

    Returns provider/text/latency and names of attempts. Cancelled provider API
    requests may still incur external charges; callers should meter dispatches.
    """
    if not workers or len(workers) > 3:
        raise ValueError("Select one to three providers")

    async def invoke(name, maker):
        started = time.monotonic()
        answer = await maker()
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Provider returned no usable answer")
        return {
            "provider": name,
            "answer": answer,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    tasks = {asyncio.create_task(invoke(name, fn)): name for name, fn in workers.items()}
    started = time.monotonic()
    failures = []
    try:
        pending = set(tasks)
        while pending:
            remain = timeout_seconds - (time.monotonic() - started)
            if remain <= 0:
                break
            done, pending = await asyncio.wait(pending, timeout=remain,
                                               return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                try:
                    winning = finished.result()
                    return {**winning, "attempted": list(workers),
                            "race_elapsed_ms": int((time.monotonic()-started)*1000)}
                except Exception:
                    failures.append(tasks[finished])
        raise RuntimeError("No AI provider returned a usable answer")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
