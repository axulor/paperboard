import anyio
import pytest

from app.sources.ratelimit import RateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.mark.anyio
async def test_first_request_goes_immediately_then_waits_out_the_interval() -> None:
    time = FakeTime()
    limiter = RateLimiter(3.0, clock=time.clock, sleep=time.sleep)

    async with limiter.slot():
        time.now += 1.0  # the request takes one second
    async with limiter.slot():
        pass

    assert time.sleeps == [2.0]


@pytest.mark.anyio
async def test_no_wait_when_the_interval_has_passed() -> None:
    time = FakeTime()
    limiter = RateLimiter(3.0, clock=time.clock, sleep=time.sleep)

    async with limiter.slot():
        pass
    time.now += 5.0
    async with limiter.slot():
        pass

    assert time.sleeps == []


@pytest.mark.anyio
async def test_only_one_request_at_a_time() -> None:
    limiter = RateLimiter(0)
    active = 0
    most = 0

    async def request() -> None:
        nonlocal active, most
        async with limiter.slot():
            active += 1
            most = max(most, active)
            await anyio.sleep(0.01)
            active -= 1

    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(request)

    assert most == 1
