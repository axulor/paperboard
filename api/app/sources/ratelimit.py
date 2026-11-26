import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager


class RateLimiter:
    """One request at a time, and at least `min_interval` seconds between request starts.

    The slot is held for the whole request, so a source that asks for a single connection
    gets one. A limiter only covers its own process: run sources that need a global limit
    from a single worker.
    """

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_start: float | None = None

    @asynccontextmanager
    async def slot(self) -> AsyncGenerator[None]:
        async with self._lock:
            if self._last_start is not None:
                wait = self._last_start + self._min_interval - self._clock()
                if wait > 0:
                    await self._sleep(wait)
            self._last_start = self._clock()
            yield
