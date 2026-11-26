"""Functions run in a child process by test_isolation.py. They must be importable."""

import os
import time


def crash() -> None:
    os._exit(3)


def hang() -> None:
    time.sleep(60)


def allocate(size: int) -> int:
    return len(bytearray(size))


def double(value: int) -> int:
    return value * 2
